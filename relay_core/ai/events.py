"""Plain-text event editor; richer sources remain available in the existing Desk form."""
import frappe
from relay_core import ai_features
from relay_core.permissions import permitted_document, require_access
from relay_core.business_access import document_name

EVENT = 'Relay AI Event'
FIELDS = ('title', 'enabled', 'company', 'description', 'event_starts_on', 'event_ends_on',
          'available_from', 'available_to')


@frappe.whitelist(methods=['GET'])
@ai_features.required
def directory(after=None):
    require_access(EVENT)
    rows = frappe.get_list(EVENT, filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS, 'memory_status'], order_by='name asc', page_length=31)
    for row in rows[:30]:
        doc = frappe.get_doc(EVENT, row.name)
        doc.check_permission('read')
        row.audience = [entry.business_doctype for entry in doc.audience]
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def save(values, name=None):
    require_access(EVENT, 'write')
    if name:
        document_name(name)
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - {*FIELDS, 'audience'}:
        raise ValueError('Invalid event fields')
    audience = values.get('audience', [])
    if not isinstance(audience, list) or not 1 <= len(audience) <= 20 or any(not isinstance(v, str) for v in audience):
        raise ValueError('Choose 1–20 audience business types')
    doc = frappe.get_doc(EVENT, name) if name else frappe.new_doc(EVENT)
    doc.update({key: value for key, value in values.items() if key != 'audience'})
    doc.set('audience', [{'business_doctype': value} for value in audience])
    doc.save()
    return {'name': doc.name}


@ai_features.required
def read(name):
    """One event with its audience, links and attached files, for API clients."""
    from relay_core.ai.event_memory import attached_files
    doc = permitted_document(EVENT, name)
    return {'name': doc.name, **{field: doc.get(field) for field in (*FIELDS, 'memory_status')},
            'audience': [row.business_doctype for row in doc.audience],
            'links': [{'url': row.url, 'note': row.note} for row in doc.links],
            'files': [{'name': row.name, 'file_name': row.file_name, 'file_size': row.file_size} for row in attached_files(name)]}


@ai_features.required
def attach(name, url=None, note=None, filename=None, content_base64=None):
    """Add one link or one private file to an event, as the Desk form does. Either change queues a memory build."""
    doc = permitted_document(EVENT, name, 'write')
    if bool(url) == bool(content_base64):
        frappe.throw('Give either a link or a file')
    if url:
        doc.append('links', {'url': url, 'note': note})
        doc.save()
    else:
        attach_file(name, filename, content_base64)
    return read(name)


def attach_file(name, filename, content_base64):
    """A private File on the event; its File hook queues the build."""
    from relay_core.ai.event_memory import MAX_FILES, attached_files, file_limit
    from relay_core.ai.event_sources import EXTENSIONS
    from relay_core.attachments import save_attachment
    from relay_core.file_limits import get_decoded_bytes
    from relay_core.template_media import plain_filename
    plain_filename(filename)
    if not filename.lower().endswith(tuple('.' + extension for extension in EXTENSIONS)):
        frappe.throw(f'Attach one of these file types: {", ".join(EXTENSIONS)}')
    if len(attached_files(name)) >= MAX_FILES:
        frappe.throw(f'Attach at most {MAX_FILES} files to an event')
    raw = get_decoded_bytes(content_base64, file_limit())
    save_attachment(filename, raw, name, EVENT)
