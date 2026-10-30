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
    """Move the chat to a newer message and count an incoming live message as unread."""
    chat = locked(key)
    values = newer_values(chat, key, message)
    if message.get('direction') == 'Incoming' and not message.get('legacy_source'):
        values.update(unread_count=(chat.unread_count or 0) + 1, is_unread=1)
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


def mark_read(key, upto=None):
    """Lower the shared unread count after a reader saw the chat up to message `upto`, or all of it when None."""
    chat = frappe.db.get_value(CHAT, {'business_doctype': key[0], 'business_name': key[1]}, FIELDS, as_dict=True, for_update=True)
    if not chat or not chat.unread_count:
        return
    unread = 0 if not upto or upto >= (chat.last_message or '') else unread_after(key, upto)
    if unread < chat.unread_count:
        frappe.db.set_value(CHAT, chat.name, {'unread_count': unread, 'is_unread': int(unread > 0)}, update_modified=False)
        changed()


def mark_unread(key):
    chat = frappe.db.get_value(CHAT, {'business_doctype': key[0], 'business_name': key[1]}, FIELDS, as_dict=True, for_update=True)
    if chat:
        frappe.db.set_value(CHAT, chat.name, {'unread_count': max(chat.unread_count or 0, 1), 'is_unread': 1},
                            update_modified=False)
        changed()


def unread_after(key, upto):
    filters = {'direction': 'Incoming', 'legacy_source': ['is', 'not set'], 'name': ['>', upto]}
    if key[0] == CONTACT:
        filters.update(relay_contact=key[1], business_name=['is', 'not set'], legacy_triage=0)
    else:
        filters.update(business_doctype=key[0], business_name=key[1])
    return frappe.db.count('Relay Message', filters)


def changed():
    """A shared read state changed: counts start over and chat lists reload. The event names no chat."""
    from relay_core.queue_counts import invalidate
    invalidate()
    frappe.publish_realtime('relay_changed', {'kind': 'chats'}, room=frappe.realtime.get_doctype_room('Relay Message'),
                            after_commit=True)


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

    A chat's unread count is its incoming live messages after the newest reply or operator read."""
    install_index()
    owners = unstamped_owners()
    latest = {}
    for message in latest_messages():
        key = key_of(message, owners)
        if key not in latest or message_order(message) > message_order(latest[key]):
            latest[key] = message
    unread = unread_counts(read_thresholds(owners), owners)
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


def read_thresholds(owners):
    """The newest outgoing or operator-read message name of each chat."""
    thresholds = {}
    statements = (f"SELECT {KEY_SQL}, MAX(name) FROM `tabRelay Message` WHERE direction='Outgoing' AND {LIVE} GROUP BY 1, 2",
                  f"""SELECT {KEY_SQL}, MAX(name) FROM `tabRelay Message` WHERE {LIVE}
                      AND name IN (SELECT message FROM `tabRelay Message Read`) GROUP BY 1, 2""")
    for statement in statements:
        for doctype, name, newest in frappe.db.sql(statement):
            key = resolve((doctype, name), owners)
            thresholds[key] = max(thresholds.get(key, ''), newest or '')
    return thresholds


def unread_counts(thresholds, owners):
    counts = {}
    rows = frappe.db.sql(f"""SELECT {KEY_SQL}, name FROM `tabRelay Message` WHERE direction='Incoming'
        AND COALESCE(legacy_source, '')='' AND {LIVE}""")
    for doctype, name, message in rows:
        key = resolve((doctype, name), owners)
        if message > thresholds.get(key, ''):
            counts[key] = counts.get(key, 0) + 1
    return counts
