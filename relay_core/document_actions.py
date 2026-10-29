"""Configured "Send on WhatsApp" actions: a button on desk forms and an API for other apps."""
import hashlib
import json
import re
import uuid

import frappe
from relay_core import document_sends
from relay_core.permissions import require_access

CACHE_KEY = 'relay_document_actions'
MAX_BUTTONS = 10


def clear_cache():
    frappe.cache.delete_value(CACHE_KEY)


def rule_view(action):
    """The action in the shape the business event helpers read."""
    return frappe._dict(source_doctype=action.document_type, parameter_mapping=action.parameter_mapping,
                        template=action.template, channel=action.channel)


def button_fields(action):
    fields = json.loads(action.get('button_mapping') or '[]')
    if not isinstance(fields, list) or len(fields) > MAX_BUTTONS or any(not isinstance(field, str) for field in fields):
        raise ValueError('URL button variables must be a list of document fields')
    meta = frappe.get_meta(action.document_type)
    unknown = [field for field in fields if field != 'name' and not meta.get_field(field)]
    if unknown:
        raise ValueError(f'Unknown {action.document_type} fields: {", ".join(unknown)}')
    return fields


def validate_action(action):
    require_access('Relay Document Action', 'write')
    from relay_core.business_events import approved, mapping
    from relay_core.business_references import RELAY_DOCTYPES
    if action.document_type in RELAY_DOCTYPES:
        raise ValueError('Choose a business document')
    if action.business_field == 'name':
        if action.document_type != action.business_doctype:
            raise ValueError('Use name only when the document is the business record')
    else:
        field = frappe.get_meta(action.document_type).get_field(action.business_field)
        if not field or field.fieldtype != 'Link' or field.options != action.business_doctype:
            raise ValueError('Business field must link to the business DocType')
    rule = rule_view(action)
    mapping(rule)
    button_fields(action)
    if action.enabled:
        approved(rule)
    document_sends.validate(action, action.document_type)


def available():
    """{doctype: [{name, label}]} of the enabled form buttons the current user may use."""
    if frappe.session.user == 'Guest' or not frappe.has_permission('Relay Contact', 'read'):
        return {}
    rows = frappe.cache.get_value(CACHE_KEY)
    if rows is None:
        roles = {}
        for row in frappe.get_all('Relay Document Action Role', fields=['parent', 'role'], limit_page_length=0):
            roles.setdefault(row.parent, []).append(row.role)
        rows = [dict(row, roles=roles.get(row.name, [])) for row in frappe.get_all('Relay Document Action',
            filters={'enabled': 1, 'show_button': 1}, fields=['name', 'document_type', 'label'], order_by='name asc')]
        frappe.cache.set_value(CACHE_KEY, rows)
    mine = set(frappe.get_roles())
    result = {}
    for row in rows:
        if not row['roles'] or mine.intersection(row['roles']):
            result.setdefault(row['document_type'], []).append({'name': row['name'], 'label': row['label']})
    return result


def boot_session(bootinfo):
    bootinfo.relay_document_actions = available()


def load(doctype, name, action_name):
    """(action, document, business record name) after the Relay, role and document checks."""
    require_access()
    if not all(isinstance(value, str) and 0 < len(value) <= 140 for value in (doctype, name, action_name)):
        frappe.throw('Choose a document and an action')
    action = frappe.get_doc('Relay Document Action', action_name)
    roles = [row.role for row in action.roles]
    if not action.enabled or action.document_type != doctype or roles and not set(roles).intersection(frappe.get_roles()):
        frappe.throw('This action is not available for this document', frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    business = doc.name if action.business_field == 'name' else doc.get(action.business_field)
    if not business:
        frappe.throw('The document has no business record to send to')
    from relay_core.business_access import business_document
    business_document(action.business_doctype, business).check_permission('read')
    return action, doc, business


def template_data(action, doc):
    """Template name, language and components filled from readable document fields."""
    from relay_core.business_events import approved, mapping, parameters, readable_parameters
    rule = rule_view(action)
    template = approved(rule)
    readable_parameters(rule, doc, json.dumps({'selection': {}}))
    components = [{'type': 'body', 'parameters': parameters(rule, doc)}] if mapping(rule) else []
    buttons = button_fields(action)
    permitted = set(frappe.get_meta(action.document_type).get_permitted_fieldnames(permission_type='read')) | {'name'}
    if not set(buttons).issubset(permitted):
        raise ValueError('Button fields are not readable')
    for index, field in enumerate(buttons):
        components.append({'type': 'button', 'sub_type': 'url', 'index': str(index),
                           'parameters': [{'type': 'text', 'text': str(doc.get(field) or '')[:2000]}]})
    return {'name': template.template_name, 'language': template.language, 'components': components}


def preview(doctype, name, action_name):
    """What the dialog shows: the filled template text, the PDF name and the contacts with their numbers."""
    from relay_core.identity import contact_identities
    from relay_core.whatsapp_templates import message_content
    action, doc, business = load(doctype, name, action_name)
    data = template_data(action, doc)
    recipients = []
    for contact in document_sends.contacts(action, doc, action.business_doctype, business):
        person = frappe.get_doc('Contact', contact)
        if person.has_permission('read'):
            recipients.append({'contact': contact, 'name': person.get('full_name') or contact,
                               'numbers': sorted(contact_identities(person)['WhatsApp'])})
    return {'action': action.name, 'label': action.label, 'template': data['name'],
            'text': message_content(data, channel=action.channel)['text'],
            'file_name': document_sends.file_name(action, doc) if action.attachment_type else None,
            'all_numbers': action.recipients == 'All business contacts', 'recipients': recipients}


def chosen_contacts(contacts, allowed):
    if contacts in (None, ''):
        return allowed
    contacts = frappe.parse_json(contacts) if isinstance(contacts, str) else contacts
    if not isinstance(contacts, list) or not contacts or not set(contacts).issubset(allowed):
        frappe.throw('Choose contacts of this business record', frappe.PermissionError)
    return [contact for contact in allowed if contact in contacts]


def send(doctype, name, action_name, contacts=None, request_key=None):
    """Send the action's template, with its PDF, to each chosen contact. One result per WhatsApp number."""
    if request_key is not None and (not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_key)):
        frappe.throw('Use a request key of at most 80 letters, digits, - or _')
    action, doc, business = load(doctype, name, action_name)
    chosen = chosen_contacts(contacts, document_sends.contacts(action, doc, action.business_doctype, business))
    if not chosen:
        frappe.throw('This business record has no contact to send to')
    template, prepared = template_data(action, doc), {}
    request_key = request_key or uuid.uuid4().hex
    results = []
    for contact in chosen:
        try:
            targets = document_sends.targets(action, contact, action.channel)
        except (ValueError, frappe.ValidationError, frappe.PermissionError) as error:
            results.append({'contact': contact, 'status': 'Skipped', 'error': str(error)})
            continue
        for target in targets:
            key = hashlib.sha256(f'{action.name}:{doctype}:{name}:{request_key}:{target[1]}'.encode()).hexdigest()
            try:
                result = earlier_send(key) or send_one(action, doc, template, prepared, target, key, business)
            except (ValueError, frappe.ValidationError, frappe.PermissionError) as error:
                result = {'status': 'Rejected', 'error': str(error)}
            results.append({'contact': contact, 'endpoint': target[1], **result})
    return {'request_key': request_key, 'results': results}


def earlier_send(key):
    """The result of an earlier send with this key, so a repeated request never sends or uploads again."""
    from relay_core import messaging
    action = frappe.db.get_value('Relay Message Action', {'request_key': hashlib.sha256(
        (frappe.session.user + ':' + key).encode()).hexdigest()}, 'name')
    return messaging.reconcile(action) if action else None


def send_one(action, doc, template, prepared, target, key, business):
    """Render and upload the PDF once per request, on the first target that needs it."""
    if action.attachment_type and not prepared:
        prepared['data'], prepared['document'] = document_sends.with_document(
            template, action.channel, *document_sends.render_pdf(action, doc))
    return document_sends.send_template(target, action.channel, prepared.get('data', template), key,
                                        (action.business_doctype, business), prepared.get('document'))
