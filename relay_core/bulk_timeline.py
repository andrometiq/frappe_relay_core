"""Campaign sends in contact timelines: one outgoing message per admitted row, written per batch."""
import frappe
from frappe.model.naming import getseries
from relay_core.automation.contracts import canonical
from relay_core.automation.provenance import conversation_key

SERIES = 'RELAY-MSG-'
FIELDS = ('name', 'creation', 'modified', 'owner', 'modified_by', 'docstatus', 'relay_contact', 'channel', 'direction',
          'status', 'content', 'message_type', 'message_data', 'sender_endpoint', 'provider_context',
          'conversation_key', 'source_key')
STATUS = {'Queued': 'Pending', 'Uncertain': 'Pending', 'Sent': 'Sent', 'Failed': 'Failed', 'Cancelled': 'Failed',
          'Delivered': 'Delivered', 'Read': 'Read'}
RANK = {'Pending': 0, 'Sent': 1, 'Failed': 2, 'Delivered': 3, 'Read': 4}
CANCELLED = 'Cancelled before sending'


def reserve(count):
    """First of count new Relay Message numbers, from a short transaction of its own. The series row is locked
    before any read, so snapshot isolation cannot refuse it, and other messages do not wait for the batch."""
    frappe.db.commit()
    first = int(getseries(SERIES, 10))
    frappe.db.sql('UPDATE `tabSeries` SET `current`=`current`+%s WHERE `name`=%s', (count - 1, SERIES))
    frappe.db.commit()
    return first


def record(doc, snapshot, rows, first):
    """Insert the sent message of rows whose number belongs to a Relay Contact; one realtime event.
    first is what reserve(len(rows)) returned. Its locks come before its first plain read."""
    from relay_core.inbox import message_created
    from relay_core.whatsapp_receipts import lock_endpoints
    people = lock_endpoints(doc.channel, sorted({row.destination for row in rows})) if rows else {}
    if people:  # message_created updates these contacts after the read below.
        frappe.db.sql('SELECT name FROM `tabRelay Contact` WHERE name IN %s ORDER BY name FOR UPDATE',
                      (tuple(set(people.values())),))
    rows = [row for row in rows if row.destination in people]
    if rows:  # A repeated push of the same keys writes nothing.
        known = set(frappe.get_all('Relay Message', filters={'source_key': ['in', [row.request_key for row in rows]]},
                                   pluck='source_key', limit_page_length=0))
        rows = [row for row in rows if row.request_key not in known]
    if not rows:
        return
    now, user, context = frappe.utils.now_datetime(), frappe.session.user, {'provider': 'WhatsApp'}
    values, latest = [], {}
    for index, row in enumerate(rows):
        name = f'{SERIES}{first + index:010d}'
        content = sent_content(doc, snapshot, row.message)
        values.append((name, now, now, user, user, 0, people[row.destination], doc.channel, 'Outgoing', 'Pending',
                       content['text'], 'text', canonical(content), row.destination, canonical(context),
                       conversation_key(doc.channel, row.destination, context), row.request_key))
        latest[people[row.destination]] = name
    frappe.db.bulk_insert('Relay Message', FIELDS, values, ignore_duplicates=True)
    for contact in sorted(latest):
        message_created(frappe._dict(relay_contact=contact, creation=now, name=latest[contact]))
    changed()


def sent_content(doc, snapshot, message):
    """Timeline content of one Hub message: the rendered template, the text, or the media kind and caption."""
    if 'message' in snapshot:
        label = snapshot['message']['kind'].capitalize()
        text = message.get('body') or ': '.join(filter(None, (label, message.get('caption'))))
        return {'kind': 'text', 'text': text, 'campaign': doc.name}
    from relay_core.whatsapp_templates import message_content
    content = message_content({'name': doc.template_name, 'language': doc.language, 'components': message['components']},
                              snapshot['template'])
    content['campaign'] = doc.name
    return content


def apply(rows):
    """Bulk update rows -> timeline message status, provider ID and failure reason. One monotonic UPDATE per status."""
    from relay_core.bulk_updates import derived
    from relay_core.message_updates import provider_key
    if not rows:
        return
    messages = frappe.get_all('Relay Message', filters={'source_key': ['in', [row['key'] for row in rows]]},
                              fields=['name', 'source_key', 'channel', 'sender_endpoint', 'relay_contact'], limit_page_length=0)
    by_key, groups = {message.source_key: message for message in messages}, {}
    for row in rows:
        message, status = by_key.get(row['key']), STATUS[row['status']]
        if message and status != 'Pending':
            identifier = row.get('message_id') or ''
            groups.setdefault(status, []).append((message.name, identifier,
                provider_key(message.channel, message.sender_endpoint, identifier) if identifier else '',
                row['reason'] or (CANCELLED if row['status'] == 'Cancelled' else '')))
    for status in sorted(groups, key=RANK.get):
        table, values = derived(('name', 'message_id', 'message_key', 'error'), groups[status])
        frappe.db.sql(f'''UPDATE `tabRelay Message` m JOIN ({table}) u ON m.name=u.name SET m.status=%s,
            m.provider_id=IF(u.message_id='', m.provider_id, u.message_id),
            m.provider_message_key=IF(u.message_id='', m.provider_message_key, u.message_key),
            m.delivery_error={'u.error' if status == 'Failed' else "''"} WHERE m.status IN %s''',
            (*values, status, tuple(name for name, rank in RANK.items() if rank < RANK[status])))
    if messages:
        changed()
    from relay_core.realtime import contact_changed
    updated = {name for group in groups.values() for name, *_ in group}
    contacts = {}
    for message in messages:
        if message.name in updated:
            contacts.setdefault(message.relay_contact, []).append(message.name)
    for contact, names in contacts.items():
        contact_changed(contact, messages=names)


def cancelled(request_key):
    frappe.db.sql('''UPDATE `tabRelay Message` SET status='Failed', delivery_error=%s
        WHERE source_key=%s AND status='Pending' ''', (CANCELLED, request_key))


def changed():
    frappe.publish_realtime('relay_changed', {'kind': 'messages'},
                            room=frappe.realtime.get_doctype_room('Relay Message'), after_commit=True)
