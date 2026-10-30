"""Document PDFs and recipients for WhatsApp template sends from business events and form actions.

The PDF is rendered as the sending user, uploaded to the Hub as private WhatsApp media and kept
as a private File on the sent Relay Message. No public File or link is created."""
import base64
import html
import json
import re

import frappe

ATTACHMENT_TYPES = ('Print Format', 'Report')
RECIPIENTS = ('Primary contact', 'All business contacts', 'Document contact field')
MAX_CONTACTS = 20
MAX_REPORT_ROWS = 2000
PLACEHOLDER = re.compile(r'\{\{\s*doc\.([A-Za-z0-9_]+)\s*\}\}')


def fill(text, doc):
    """Text with each {{doc.field}} replaced by the document value."""
    return PLACEHOLDER.sub(lambda match: '' if doc.get(match.group(1)) is None else str(doc.get(match.group(1))), text or '')


def report_filters(config, doc):
    """Report filters with placeholders filled. A value that is only a placeholder keeps the field's type."""
    filters = json.loads(config.get('report_filters') or '{}')
    if not isinstance(filters, dict):
        raise ValueError('Report filters must be a JSON object')

    def resolve(value):
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, str):
            return value
        whole = PLACEHOLDER.fullmatch(value.strip())
        return doc.get(whole.group(1)) if whole else fill(value, doc)

    return {key: resolve(value) for key, value in filters.items()}


def file_name(config, doc):
    name = fill(config.get('file_name') or '{{doc.name}}', doc)
    name = re.sub(r'[^A-Za-z0-9 ._-]', '_', name).strip(' ._')[:110] or 'document'
    return name if name.lower().endswith('.pdf') else name + '.pdf'


def validate(config, doctype):
    """Check the attachment and recipient settings of a rule or form action for `doctype`."""
    meta = frappe.get_meta(doctype)
    known = {'name'} | {field.fieldname for field in meta.fields}
    for text in (config.get('file_name'), config.get('report_filters')):
        unknown = set(PLACEHOLDER.findall(text or '')) - known
        if unknown:
            raise ValueError(f'Unknown {doctype} fields: {", ".join(sorted(unknown))}')
    kind = config.get('attachment_type')
    if kind == 'Print Format':
        if frappe.db.get_value('Print Format', config.get('print_format'), 'doc_type') != doctype:
            raise ValueError(f'Choose a print format of {doctype}')
    elif kind == 'Report':
        if not config.get('report_name') or not frappe.db.exists('Report', config.report_name):
            raise ValueError('Choose a report')
        report_filters(config, frappe._dict())
    elif kind:
        raise ValueError('Attach a print format or a report')
    mode = config.get('recipients')
    if mode and mode not in RECIPIENTS:
        raise ValueError('Choose who receives the message')
    if mode == 'Document contact field':
        field = meta.get_field(config.get('contact_field'))
        if not field or field.fieldtype != 'Link' or field.options != 'Contact':
            raise ValueError('Contact field must link to Contact')


def render_pdf(config, doc):
    """(file name, PDF bytes) rendered with the current user's print or report permission."""
    if config.get('attachment_type') == 'Print Format':
        doc.check_permission('print')
        raw = frappe.get_print(doc.doctype, doc.name, config.print_format, doc=doc, as_pdf=True)
    else:
        raw = report_pdf(config.report_name, report_filters(config, doc))
    from relay_core.file_limits import get_media_max_bytes, size_error
    if error := size_error(len(raw), get_media_max_bytes('WhatsApp', 'document'), 'The PDF'):
        raise ValueError(error)
    return file_name(config, doc), raw


def report_pdf(report_name, filters):
    from frappe.desk.query_report import run
    from frappe.utils.pdf import get_pdf
    result = run(report_name, filters=filters, ignore_prepared_report=True)
    columns = [report_column(column) for column in result.get('columns') or []]
    columns = [column for column in columns if not column.get('hidden')]
    rows = [row for row in result.get('result') or [] if isinstance(row, (dict, list, tuple))][:MAX_REPORT_ROWS]
    head = ''.join(f'<th>{html.escape(column["label"])}</th>' for column in columns)
    body = ''.join('<tr>' + ''.join(f'<td>{report_cell(row, index, column)}</td>' for index, column in enumerate(columns)) + '</tr>'
                   for row in rows)
    summary = ', '.join(f'{key}: {value}' for key, value in filters.items() if value not in (None, '', []))
    page = (f'<h3>{html.escape(report_name)}</h3><p>{html.escape(summary)}</p>'
            '<style>table{border-collapse:collapse;width:100%;font-size:9px}th,td{border:1px solid #ccc;padding:3px}</style>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')
    return get_pdf(page, {'orientation': 'Landscape'})


def report_column(column):
    if isinstance(column, dict):
        return dict(column, label=str(column.get('label') or column.get('fieldname') or ''))
    label, _, rest = str(column).partition(':')
    return {'label': label, 'fieldname': frappe.scrub(label), 'fieldtype': rest.split('/')[0].split(':')[0] or 'Data'}


def report_cell(row, index, column):
    value = row.get(column.get('fieldname')) if isinstance(row, dict) else (row[index] if index < len(row) else None)
    if value is None:
        return ''
    return html.escape(str(frappe.format_value(value, frappe._dict(column))))


def upload(channel, name, raw, media_type='document', mime_type='application/pdf'):
    """Hub media id of the file, uploaded through the channel's WhatsApp number."""
    from relay_core.hub_channels import hub_arguments
    from relay_core.whatsapp import HubError, client
    result = client().execute(hub_arguments(channel, {'operation': 'messages.media_upload',
        'media_type': media_type, 'mime_type': mime_type, 'filename': name,
        'content_base64': base64.b64encode(raw).decode()}))
    media_id = str(result.get('id') or '')
    if not re.fullmatch(r'[0-9]{1,100}', media_id):
        raise HubError('Hub returned no media id')
    return media_id


def has_document_header(template, channel):
    from relay_core.whatsapp_templates import definition
    found = definition(template['name'], template.get('language') or '', channel) or {}
    return any(str(part.get('type') or '').upper() == 'HEADER' and str(part.get('format') or '').upper() == 'DOCUMENT'
               for part in found.get('components') or [])


def with_document(template, channel, name, raw):
    """(template data, document) carrying the PDF; document is (name, bytes, follow-up message or None).

    A template with a document header carries the PDF there. Otherwise the PDF follows as a
    document message, which WhatsApp accepts only while the customer service window is open."""
    media_id = upload(channel, name, raw)
    document = {'id': media_id, 'filename': name}
    if has_document_header(template, channel):
        header = {'type': 'header', 'parameters': [{'type': 'document', 'document': document}]}
        return dict(template, components=[header, *(template.get('components') or [])]), (name, raw, None)
    follow = {'operation': 'messages.media', 'arguments': {'media_type': 'document', 'media_id': media_id, 'filename': name}}
    return template, (name, raw, follow)


def keep_copy(result, name, raw):
    """Attach the sent PDF to the Relay Message of `result`, so the chat can open it."""
    request_key = frappe.db.get_value('Relay Message Action', result.get('action'), 'request_key') if result.get('action') else None
    message = frappe.db.get_value('Relay Message', {'source_key': request_key}, 'name') if request_key else None
    data = json.loads(frappe.db.get_value('Relay Message', message, 'message_data') or '{}') if message else {}
    if not message or data.get('attachment'):
        return message
    from frappe.utils.file_manager import save_file
    file = save_file(name, raw, 'Relay Message', message, is_private=1)
    data.update(attachment=file.name, attachment_source=message)
    frappe.db.set_value('Relay Message', message, 'message_data', json.dumps(data, ensure_ascii=False), update_modified=False)
    return message


def send_template(target, channel, template, request_key, business, document=None):
    """Send `template` to one (contact, endpoint) target, then the PDF as a follow-up when its header cannot carry it.

    `document` is (file name, PDF bytes, follow-up message or None) from `with_document`."""
    from relay_core.conversation_start import send_business
    contact, endpoint = target
    options = {'endpoint': endpoint} if endpoint else {}
    result = send_business(contact, channel, 'template', template, request_key, *business, **options)
    if not document:
        return result
    name, raw, follow = document
    keep_copy(result, name, raw)
    if follow and result.get('status') in ('Submitted', 'Queued'):
        try:
            extra = send_business(contact, channel, 'whatsapp', follow, request_key[:110] + '-pdf', *business, **options)
            keep_copy(extra, name, raw)
            result['document'] = extra
        except (ValueError, frappe.ValidationError, frappe.PermissionError) as error:
            result['document'] = {'status': 'Rejected', 'error': str(error)}
    return result


def contacts(config, doc, business_doctype, business_name):
    """Frappe Contacts that receive the document: the primary contact, all linked contacts or a document field."""
    mode = config.get('recipients')
    if mode == 'Document contact field':
        return [doc.get(config.contact_field)] if doc.get(config.contact_field) else []
    linked = frappe.get_all('Contact', filters=[['Dynamic Link', 'link_doctype', '=', business_doctype],
        ['Dynamic Link', 'link_name', '=', business_name]], pluck='name', distinct=True,
        order_by='is_primary_contact desc, creation asc', limit_page_length=MAX_CONTACTS)
    if mode != 'Primary contact' or not linked:
        return linked
    meta = frappe.get_meta(business_doctype)
    primary = frappe.db.get_value(business_doctype, business_name, 'customer_primary_contact') if meta.get_field('customer_primary_contact') else None
    return [primary if primary in linked else linked[0]]


def targets(config, contact, channel):
    """(contact, endpoint) pairs: every verified number for 'All business contacts', else the mobile number first."""
    from relay_core.identity import phone_number
    relay = relay_ready(contact, channel)
    rows = frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': relay, 'channel': channel, 'verified': 1},
                          fields=['name', 'endpoint'], order_by='creation asc', limit_page_length=MAX_CONTACTS)
    if not rows:
        raise ValueError(f'Contact {contact} has no WhatsApp number on this channel')
    if config.get('recipients') == 'All business contacts':
        return [(contact, row.name) for row in rows]
    mobile = phone_number(frappe.db.get_value('Contact', contact, 'mobile_no') or '')
    return [(contact, next((row.name for row in rows if row.endpoint == mobile), rows[0].name))]


def relay_ready(contact, channel):
    """The Relay contact of a Frappe Contact, with its WhatsApp numbers verified on the channel.

    The numbers come from the Contact itself; a number bound to someone else is never taken over."""
    from relay_core.contact_lifecycle import enroll, relay_contact
    from relay_core.identity import contact_identities
    person = frappe.get_doc('Contact', contact)
    person.check_permission('read')
    numbers = sorted(contact_identities(person)['WhatsApp'])
    relay = relay_contact(contact)
    if not relay:
        if not numbers:
            raise ValueError(f'Contact {contact} has no WhatsApp number')
        relay = frappe.get_doc({'doctype': 'Relay Contact', 'contact': contact,
            'display_name': person.get('full_name') or contact}).insert(ignore_permissions=True).name
    for number in numbers:
        enroll(relay, channel, 'WhatsApp', number)
    return relay
