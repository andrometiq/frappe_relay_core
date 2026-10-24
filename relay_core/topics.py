"""Permission-scoped conversation topics; automatic updates preserve human edits."""
import hashlib
import json
import uuid

import frappe

from relay_core.permissions import readable_contact, require_access

STATUSES = {'Open', 'Waiting', 'Resolved', 'Archived'}
SOURCES = {'Manual', 'Flow', 'External AI', 'Import'}


def _messages(contact, names):
    if not isinstance(names, list) or len(names) > 500 or any(not isinstance(n, str) for n in names):
        frappe.throw('Choose at most 500 messages')
    names = list(dict.fromkeys(names))
    for name in names:
        message = frappe.get_doc('Relay Message', name)
        message.check_permission('read')
        if message.relay_contact != contact:
            frappe.throw('Message belongs to another conversation', frappe.PermissionError)
        frappe.get_doc('Relay Channel', message.channel).check_permission('read')
    return names


def _view(doc):
    from relay_core.collaboration import authorize
    authorize(doc)
    names = doc.messages if isinstance(doc.messages, list) else json.loads(doc.messages or '[]')
    # Recheck message/channel access: a topic must not bypass later permission changes.
    _messages(doc.relay_contact, names)
    return {**{key: doc.get(key) for key in ('name', 'relay_contact', 'title', 'summary', 'category', 'status', 'source', 'human_edited', 'modified')},
            'messages': names, 'message_count': len(names)}


@frappe.whitelist(methods=['GET'])
def directory(contact, after=None):
    require_access()
    readable_contact(contact)
    filters = {'relay_contact': contact}
    if after:
        filters['name'] = ['<', after]
    rows = frappe.get_all('Relay Conversation Topic', filters=filters, pluck='name', order_by='name desc', limit_page_length=31)
    items=[]
    for name in rows[:30]:
        try: items.append(_view(frappe.get_doc('Relay Conversation Topic', name)))
        except frappe.PermissionError: continue
    return {'items': items,
            'next': rows[29] if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
def save(contact, values, name=None, request_key=None):
    require_access()
    readable_contact(contact)
    if isinstance(values, str):
        values = frappe.parse_json(values)
    if not isinstance(values, dict) or set(values) - {'title', 'summary', 'category', 'status', 'messages', 'modified', 'business_doctype', 'business_name'}:
        frappe.throw('Unsupported topic fields')
    if request_key is not None and (not isinstance(request_key, str) or not 1 <= len(request_key) <= 140):
        frappe.throw('Invalid topic request key')
    source_key = json.dumps([frappe.session.user, request_key]) if request_key and not name else None
    return upsert(contact, values, name=name, source='Manual', source_key=source_key)


def upsert(contact, values, *, name=None, source='Flow', source_key=None):
    """Internal automation entry point runs with its configured execution user's access."""
    require_access()
    readable_contact(contact)
    if source not in SOURCES:
        frappe.throw('Unsupported topic source')
    if source != 'Manual' and (not isinstance(source_key, str) or not 1 <= len(source_key) <= 500):
        frappe.throw('Automatic topics require a stable source key')
    title = values.get('title', '')
    summary = values.get('summary', '')
    category = values.get('category', '')
    status = values.get('status', 'Open')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 140:
        frappe.throw('Enter a topic title of 1–140 characters')
    if not isinstance(summary, str) or len(summary) > 10000 or not isinstance(category, str) or len(category) > 140:
        frappe.throw('Topic summary or category is too long')
    if status not in STATUSES:
        frappe.throw('Unsupported topic status')
    names = _messages(contact, values.get('messages', []))
    from relay_core.collaboration import business_scope, authorize
    business = business_scope(contact, names, values.get('business_doctype'), values.get('business_name'))
    intent = hashlib.sha256(json.dumps([title.strip(), summary.strip(), category.strip(), status, sorted(names), business], ensure_ascii=False).encode()).hexdigest()
    key = hashlib.sha256(json.dumps([contact, source, source_key or str(uuid.uuid4())]).encode()).hexdigest()
    # Serialize topic membership updates across both human and automation requests.
    with frappe.cache.lock('relay-topics-' + hashlib.sha256(contact.encode()).hexdigest(), timeout=30, blocking_timeout=5):
        existing = name or frappe.db.get_value('Relay Conversation Topic', {'topic_key': key}, 'name')
        doc = frappe.get_doc('Relay Conversation Topic', existing) if existing else frappe.new_doc('Relay Conversation Topic')
        if existing:
            authorize(doc)
            if (doc.get('business_doctype'), doc.get('business_name')) != business:
                frappe.throw('Topic belongs to another business', frappe.PermissionError)
            if doc.relay_contact != contact:
                frappe.throw('Topic belongs to another conversation', frappe.PermissionError)
            if source != 'Manual' and doc.topic_key != key:
                frappe.throw('Topic belongs to another source', frappe.PermissionError)
            if source == 'Manual' and source_key and not name:
                attributes = doc.attributes if isinstance(doc.attributes, dict) else json.loads(doc.attributes or '{}')
                if attributes.get('creation_intent') != intent:
                    frappe.throw('This request already created a different topic. Reload topics before continuing.')
                return _view(doc)
            if source == 'Manual' and str(values.get('modified', '')) != str(doc.modified):
                frappe.throw('This topic changed. Reload it before saving.')
            if source != 'Manual' and doc.human_edited:
                return {**_view(doc), 'preserved': True}
            if source != 'Manual':
                previous = doc.messages if isinstance(doc.messages, list) else json.loads(doc.messages or '[]')
                names = _messages(contact, list(dict.fromkeys(previous + names)))
        else:
            doc.topic_key = key
            doc.relay_contact = contact
            if source == 'Manual' and source_key:
                doc.attributes = json.dumps({'creation_intent': intent})
        # A message belongs to one topic within its contact, matching legacy behavior.
        if membership_conflict(contact,names,exclude=doc.name):
            frappe.throw('A selected message already belongs to another topic')
        doc.business_doctype, doc.business_name = business
        doc.title = title.strip()
        doc.summary = summary.strip()
        doc.category = category.strip()
        doc.status = status
        doc.source = source
        doc.human_edited = source == 'Manual'
        doc.messages = json.dumps(names)
        doc.save(ignore_permissions=True)
        from relay_core.realtime import contact_changed
        contact_changed(contact,'topics')
        frappe.db.commit()
        return _view(doc)


def membership_conflict(contact,names,exclude=None):
    """Check JSON membership in the database without hydrating other topics."""
    if not names:return False
    if len(names)>500:frappe.throw('Choose at most 500 messages')
    values={'contact':contact,'exclude':exclude or ''}
    maria=[];postgres=[]
    for index,name in enumerate(names):
        key='message_'+str(index)
        values[key]=json.dumps([name])
        maria.append("JSON_CONTAINS(COALESCE(messages, '[]'), %("+key+")s)")
        postgres.append("(COALESCE(messages, '[]')::jsonb @> %("+key+")s::jsonb)")
    rows=frappe.db.multisql({
        'mariadb':'SELECT name FROM `tabRelay Conversation Topic` WHERE relay_contact=%(contact)s AND name<>%(exclude)s AND ('+' OR '.join(maria)+') LIMIT 1',
        'postgres':'SELECT name FROM "tabRelay Conversation Topic" WHERE relay_contact=%(contact)s AND name<>%(exclude)s AND ('+' OR '.join(postgres)+') LIMIT 1',
    },values=values)
    return bool(rows)
