"""Relay Chat rows: one per business record, and one per chat whose messages name no record.

The Relay Message after_insert hook keeps each row current and the operator read paths lower its shared
unread count, so the inbox list reads one table."""
import frappe

CHAT = 'Relay Chat'
CONTACT = 'Relay Contact'
FIELDS = ['name', 'last_message', 'last_message_at', 'unread_count']
PREVIEW_FIELDS = ['name', 'relay_contact', 'channel', 'direction', 'sent_at', 'creation', 'content', 'message_data',
                  'transcript', 'business_doctype', 'business_name']


def key_of(message, owners=None):
    """The (doctype, name) chat of a message: its business record, else the record that owns its contact's unstamped
    messages as in the record's thread, else its Relay Contact. Triage messages have none.

    `owners` maps a Relay Contact to that owning record, or None, when the caller has them."""
    if message.get('legacy_triage'):
        return None
    if message.get('business_doctype') and message.get('business_name'):
        return message.get('business_doctype'), message.get('business_name')
    contact = message.get('relay_contact')
    if owners is None:
        from relay_core.business_access import primary
        owners = {contact: primary(contact)}
    return owners.get(contact) or (CONTACT, contact)


def on_message(doc, method=None):
    key = key_of(doc)
    if key:
        record(key, doc)


def record(key, message):
    """Move the chat to a newer message and count an incoming live message as unread; a reply answers its thread."""
    chat = locked(key)
    values = newer_values(chat, key, message)
    if message.get('direction') == 'Incoming' and not message.get('legacy_source'):
        values.update(unread_count=(chat.unread_count or 0) + 1, is_unread=1)
    elif message.get('direction') == 'Outgoing' and chat.unread_count:
        unread = unread_total(key)
        if unread < chat.unread_count:
            values.update(unread_count=unread, is_unread=int(unread > 0))
    if values:
        frappe.db.set_value(CHAT, chat.name, values, update_modified=False)


def newer_values(chat, key, message):
    """The row values of `message` when it is newer than the chat's last message, else none."""
    stamp = frappe.utils.get_datetime(message.get('sent_at') or message.creation)
    current = (frappe.utils.get_datetime(chat.last_message_at), chat.last_message or '') if chat.last_message_at else None
    if current is not None and (stamp, message.name) <= current:
        return {}
    return dict(latest_values(message, stamp), title=title(key))


def merge(contact, key):
    """The chat's messages now belong to record `key`, so the record's row takes over the chat's row."""
    old = frappe.db.get_value(CHAT, {'business_doctype': CONTACT, 'business_name': contact}, FIELDS, as_dict=True, for_update=True)
    if not old:
        return
    chat = locked(key)
    values = newer_values(chat, key, frappe.get_doc('Relay Message', old.last_message)) if old.last_message else {}
    unread = (chat.unread_count or 0) + (old.unread_count or 0)
    frappe.db.set_value(CHAT, chat.name, dict(values, unread_count=unread, is_unread=int(unread > 0)), update_modified=False)
    frappe.db.delete(CHAT, {'name': old.name})


def latest_values(message, stamp):
    from relay_core.inbox import directory_preview
    return {'last_message': message.name, 'last_message_at': stamp, 'last_contact': message.get('relay_contact'),
            'last_channel': message.get('channel'), 'last_message_preview': directory_preview(message)}


def locked(key):
    """The chat row of a key, created when missing, locked until the transaction ends.

    The unique (business_doctype, business_name) index makes a concurrent first message reuse the same row."""
    filters = {'business_doctype': key[0], 'business_name': key[1]}
    chat = frappe.db.get_value(CHAT, filters, FIELDS, as_dict=True, for_update=True)
    if chat:
        return chat
    insert([(*key, title(key))])
    return frappe.db.get_value(CHAT, filters, FIELDS, as_dict=True, for_update=True)


def insert(rows, values=()):
    """Insert new chat rows of (doctype, name, title, *values); `values` names the extra columns."""
    now, user = frappe.utils.now_datetime(), frappe.session.user
    frappe.db.bulk_insert(CHAT, ['name', 'creation', 'modified', 'owner', 'modified_by', 'business_doctype', 'business_name',
                                 'title', *values],
                          [(frappe.generate_hash(length=12), now, now, user, user, *row) for row in rows], ignore_duplicates=True)


def title(key):
    doctype, name = key
    if doctype == CONTACT:
        row = frappe.db.get_value(CONTACT, name, ['display_name', 'contact'], as_dict=True) or {}
        return row.get('display_name') or row.get('contact') or name
    from relay_core.business_groups import title_field
    field = title_field(doctype)
    return (frappe.db.get_value(doctype, name, field) if field != 'name' else None) or name


def mark_read(key, *, everything=False):
    """Count the chat's unread messages again after a reader stored the reads of the messages they saw.

    `everything` marks the whole chat read: the reader reads the newest message of each unread thread."""
    chat = frappe.db.get_value(CHAT, {'business_doctype': key[0], 'business_name': key[1]}, FIELDS, as_dict=True, for_update=True)
    if not chat or not chat.unread_count:
        return
    if everything:
        from relay_core.message_reads import insert_reads
        insert_reads([(thread[0], newest) for thread, (_, _, newest) in thread_unread(key).items()])
    unread = unread_total(key)
    if unread < chat.unread_count:
        frappe.db.set_value(CHAT, chat.name, {'unread_count': unread, 'is_unread': int(unread > 0)}, update_modified=False)
        changed()


def mark_unread(key):
    chat = frappe.db.get_value(CHAT, {'business_doctype': key[0], 'business_name': key[1]}, FIELDS, as_dict=True, for_update=True)
    if chat:
        frappe.db.set_value(CHAT, chat.name, {'unread_count': max(chat.unread_count or 0, 1), 'is_unread': 1},
                            update_modified=False)
        changed()


def unread_total(key):
    return sum(count for count, _, _ in thread_unread(key).values())


def thread_unread(key):
    """{(relay_contact, channel, endpoint): (unread count, first unread, newest unread)} of the chat's unread threads."""
    return unread_by_thread(*chat_condition(key))


def unread_by_chat(keys):
    """thread_unread of several chats in one query: {(doctype, name): {(relay_contact, channel, endpoint): (count, first, newest)}}."""
    if not keys:
        return {}
    parts, values = [], {}
    for index, key in enumerate(keys):
        where, params = chat_condition(key)
        for name in params:
            where = where.replace(f'%({name})s', f'%({name}_{index})s')
        parts.append(f'({where})')
        values.update({f'{name}_{index}': value for name, value in params.items()})
    # Each message's chat: its business record, else its contact, as chat_condition splits them.
    chat = [f"IF(COALESCE(m.business_name, '')='', '{CONTACT}', m.business_doctype)",
            "IF(COALESCE(m.business_name, '')='', m.relay_contact, m.business_name)"]
    result = {}
    for row in unread_threads(' OR '.join(parts), values, chat):
        result.setdefault((row[0], row[1]), {})[tuple(row[2:5])] = tuple(row[5:])
    return result


def unread_by_thread(where, values=None):
    """thread_unread of the messages matching `where`."""
    return {tuple(row[:3]): tuple(row[3:]) for row in unread_threads(where, values)}


def chat_condition(key):
    """The SQL condition, on alias m, of the messages whose incoming ones the chat's unread count covers."""
    if key[0] == CONTACT:
        return ("m.relay_contact=%(contact)s AND COALESCE(m.business_name, '')='' AND COALESCE(m.legacy_triage, 0)=0",
                {'contact': key[1]})
    return 'm.business_doctype=%(doctype)s AND m.business_name=%(name)s', {'doctype': key[0], 'name': key[1]}


def unread_threads(where, values=None, key=()):
    """Rows of (*key, relay_contact, channel, endpoint, unread count, first unread, newest unread) for the threads of the
    messages matching `where` (SQL on alias m) that have unread messages. `key` adds SQL columns of m to group by.

    This is the one unread rule: a thread is one contact endpoint on one channel, and its unread messages are its live
    incoming messages after the newest reply or operator read on that thread. Each thread keeps its own position, so
    reading or answering one thread never hides the unread messages of another."""
    columns = [*key, 'm.relay_contact', 'm.channel', "COALESCE(m.sender_endpoint, '')"]
    groups = ', '.join(str(index) for index in range(1, len(columns) + 1))
    return frappe.db.sql(f"""SELECT {', '.join(columns)}, COUNT(*), MIN(m.name), MAX(m.name) FROM `tabRelay Message` m
        LEFT JOIN (SELECT x.relay_contact AS thread_contact, x.channel AS thread_channel,
                COALESCE(x.sender_endpoint, '') AS thread_endpoint, MAX(x.name) AS seen
            FROM `tabRelay Message` x
            WHERE x.relay_contact IN (SELECT m.relay_contact FROM `tabRelay Message` m WHERE {where})
                AND (x.direction='Outgoing' OR x.name IN (SELECT message FROM `tabRelay Message Read`))
            GROUP BY 1, 2, 3) c
            ON c.thread_contact=m.relay_contact AND c.thread_channel=m.channel AND c.thread_endpoint=COALESCE(m.sender_endpoint, '')
        WHERE ({where}) AND m.direction='Incoming' AND COALESCE(m.legacy_source, '')='' AND m.name>COALESCE(c.seen, '')
        GROUP BY {groups}""", values or {})


def changed():
    """A shared read state changed: counts start over and chat lists reload. The event names no chat."""
    from relay_core.queue_counts import invalidate
    invalidate()
    from relay_core.realtime import readers_changed
    readers_changed({'kind': 'chats'}, 'Relay Message')


def install_index():
    frappe.db.add_unique(CHAT, ['business_doctype', 'business_name'], 'relay_chat_record')


def query(user=None):
    """Business types and shared unlinked chats, with scope applied before pagination."""
    from relay_core.business_access import explicit_condition, relay_user
    if not relay_user(user): return '1=0'
    table = '`tabRelay Chat`'
    records = explicit_condition(CHAT, user)
    if not records: records = '1=1'
    contacts = frappe.qb.get_query(CONTACT, fields=['name'], ignore_permissions=False, user=user, order_by='').get_sql()
    return f"({records} OR ({table}.business_doctype='{CONTACT}' AND {table}.business_name IN ({contacts})))"


def permission(doc, user=None, permission_type=None):
    """The document twin of `query`, so a chat row is never read outside the list's scope."""
    condition = query(user)
    if not condition:
        return True
    return bool(frappe.db.sql(f'SELECT 1 FROM `tabRelay Chat` WHERE name=%s AND {condition}', doc.name))


def rebuild():
    """Build every chat row from the stored messages; run again, it rewrites the same derived values.

    A chat's unread count is the sum of its threads' unread messages, by the one rule in unread_threads."""
    install_index()
    owners = unstamped_owners()
    latest = {}
    for message in latest_messages():
        key = key_of(message, owners)
        if key not in latest or message_order(message) > message_order(latest[key]):
            latest[key] = message
    unread = unread_counts(owners)
    existing = {(row.business_doctype, row.business_name): row.name
                for row in frappe.get_all(CHAT, fields=['name', 'business_doctype', 'business_name'], limit_page_length=0)}
    columns = ['last_message', 'last_message_at', 'last_contact', 'last_channel', 'last_message_preview', 'unread_count', 'is_unread']
    new = []
    for key, message in latest.items():
        values = latest_values(message, frappe.utils.get_datetime(message.sent_at or message.creation))
        values.update(unread_count=unread.get(key, 0), is_unread=int(unread.get(key, 0) > 0), title=title(key))
        if key in existing:
            frappe.db.set_value(CHAT, existing.pop(key), values, update_modified=False)
        else:
            new.append((*key, values.pop('title'), *(values[column] for column in columns)))
    if new:
        insert(new, columns)
    stale = [name for (doctype, _), name in existing.items() if doctype == CONTACT]
    if stale:
        frappe.db.delete(CHAT, {'name': ['in', stale]})
    return {'chats': len(latest), 'created': len(new), 'updated': len(latest) - len(new), 'removed': len(stale),
            'unread': sum(1 for total in unread.values() if total)}


def message_order(message):
    return frappe.utils.get_datetime(message.sent_at or message.creation), message.name


STAMPED = "COALESCE(business_doctype, '')<>'' AND COALESCE(business_name, '')<>''"
KEY_SQL = (f"CASE WHEN {STAMPED} THEN business_doctype ELSE '{CONTACT}' END, "
           f"CASE WHEN {STAMPED} THEN business_name ELSE relay_contact END")
LIVE = 'COALESCE(legacy_triage, 0)=0'
STAMPED_M = "COALESCE(m.business_doctype, '')<>'' AND COALESCE(m.business_name, '')<>''"
LIVE_M = 'COALESCE(m.legacy_triage, 0)=0'


def unstamped_owners():
    """The record that owns each contact's unstamped messages, as business_access.primary decides, or None."""
    from relay_core.business_access import primary
    contacts = frappe.db.sql(f'SELECT DISTINCT relay_contact FROM `tabRelay Message` WHERE NOT ({STAMPED}) AND {LIVE}', pluck=True)
    return {contact: primary(contact) for contact in contacts}


def resolve(key, owners):
    return (owners.get(key[1]) or key) if key[0] == CONTACT else key


def latest_messages():
    """The newest message of each contact and record."""
    newest = frappe.db.sql(f"""SELECT name FROM (SELECT name, ROW_NUMBER() OVER (PARTITION BY {KEY_SQL}
        ORDER BY COALESCE(sent_at, creation) DESC, name DESC) position FROM `tabRelay Message` WHERE {LIVE}) ranked
        WHERE position=1""", pluck=True)
    return frappe.get_all('Relay Message', filters={'name': ['in', newest]}, fields=PREVIEW_FIELDS, limit_page_length=0) if newest else []


def unread_counts(owners):
    """The unread count of every chat, by the one rule in unread_threads."""
    counts = {}
    for doctype, name, *_, count, _, _ in unread_threads(LIVE_M, key=[
            f"CASE WHEN {STAMPED_M} THEN m.business_doctype ELSE '{CONTACT}' END",
            f"CASE WHEN {STAMPED_M} THEN m.business_name ELSE m.relay_contact END"]):
        key = resolve((doctype, name), owners)
        counts[key] = counts.get(key, 0) + count
    return counts
