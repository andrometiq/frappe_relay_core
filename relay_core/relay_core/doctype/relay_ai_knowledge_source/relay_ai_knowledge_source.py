import json

import frappe
from frappe.model.document import Document

from relay_core import ai_features

BASE = 'Relay AI Knowledge Base'
REQUIRED = {'Text': 'content', 'File': 'file', 'URL': 'url', 'DocType': 'reference_doctype', 'Event': 'event'}
MAX_CONTENT_FIELDS = 20
APPROVAL = ('approved_hash', 'approved_by', 'approved_on')


class RelayAIKnowledgeSource(Document):
    def validate(self):
        if not self.flags.approving:
            # Only `approve` sets the approval; a form or REST save keeps the stored values.
            for name in APPROVAL:
                self.set(name, None if self.is_new() else self.get_db_value(name))
        field = REQUIRED[self.source_type]
        if not self.get(field):
            frappe.throw(f'Set {self.meta.get_label(field)} for a {self.source_type} source')
        if not 200 <= (self.chunk_size or 0) <= 4000 or not 0 <= (self.chunk_overlap or 0) < self.chunk_size / 2:
            frappe.throw('Use a chunk size from 200 to 4000 and an overlap below half of it')
        if self.auto_sync and self.source_type not in ('DocType', 'URL'):
            self.auto_sync = 0
        if self.source_type == 'DocType':
            validate_doctype_source(self, frappe.get_doc(BASE, self.knowledge_base))
            self.current_hash = config_hash(self, frappe.get_doc(BASE, self.knowledge_base))

    def on_update(self):
        from relay_core.ai.knowledge_base.ingest import queue_sync
        if self.source_type != 'DocType' or self.approved_hash == self.current_hash:
            queue_sync(self.name)

    def on_trash(self):
        from relay_core.ai.knowledge_base import store
        store.delete(self.name)


def content_fields(source) -> list[str]:
    return [line.strip() for line in (source.content_fields or '').splitlines() if line.strip()]


def filters_of(source) -> dict:
    value = json.loads(source.filters) if isinstance(source.filters, str) and source.filters.strip() else source.filters or {}
    if not isinstance(value, dict):
        raise ValueError('Write the filters as one JSON object')
    return value


def validate_doctype_source(source, base) -> None:
    """Rows are copied into chunks, so the fields are scalar and not sensitive, and a customer knowledge base
    either ties each row to its business or holds company neutral reference data."""
    from frappe_tools.ai.tools import get_readable_meta, is_sensitive_field
    from relay_core.ai.capabilities import UNREADABLE
    from relay_core.ai.tools import company_neutral
    if not base.run_as_user:
        frappe.throw('Set Run as user on the knowledge base before adding a DocType source')
    try:
        check_audience(source, base)
    except ValueError as error:
        frappe.throw(f'{error} and cannot be a customer source')
    meta = get_readable_meta(source.reference_doctype)
    fields = content_fields(source)
    if not 1 <= len(fields) <= MAX_CONTENT_FIELDS or len(set(fields)) != len(fields):
        frappe.throw(f'Name 1 to {MAX_CONTENT_FIELDS} distinct content fields')
    for name in fields:
        field = meta.get_field(name)
        if (name != 'name' and (not field or field.fieldtype in UNREADABLE)) or is_sensitive_field(name):
            frappe.throw(f'Field {name} is not a readable scalar field')
    try:
        filters_of(source)
    except ValueError as error:
        frappe.throw(str(error))
    if source.business_field:
        field = meta.get_field(source.business_field)
        if not field or field.fieldtype != 'Link':
            frappe.throw('The business field must be a Link field to the business')
    elif base.audience == 'customer':
        try:
            company_neutral(source.reference_doctype)
        except ValueError:
            frappe.throw('A customer knowledge base needs a business field unless the DocType is company neutral')


def check_audience(source, base) -> None:
    """A customer knowledge base never holds a staff-only DocType. Save, ingest and search all check it, so a source
    saved before this rule is skipped too."""
    from relay_core.ai.tools import check_customer_doctype
    if base.audience == 'customer':
        check_customer_doctype(source.reference_doctype)


def config_hash(source, base) -> str:
    """Everything that decides which rows reach which audience; a new value needs a new approval."""
    from relay_core.ai.knowledge_base.store import content_hash
    return content_hash(json.dumps(dict(doctype=source.reference_doctype, filters=filters_of(source),
        fields=content_fields(source), business_field=source.business_field or '', audience=base.audience,
        company=base.company or '', user=base.run_as_user or '', knowledge_base=base.name), sort_keys=True))


def is_approved(source, base) -> bool:
    """The exact configuration is approved, a customer source holds no staff-only DocType, and a customer source
    without a business field still holds company neutral reference data (a new Company or a settings change ends
    that)."""
    from relay_core.ai.tools import company_neutral
    if source.source_type != 'DocType':
        return True
    try:
        check_audience(source, base)
        if base.audience == 'customer' and not source.business_field:
            company_neutral(source.reference_doctype)
        return bool(source.approved_hash) and source.approved_hash == config_hash(source, base)
    except ValueError:
        return False


@frappe.whitelist(methods=['POST'])
@ai_features.required
def approve(name: str) -> dict:
    """A manager approves the exact configuration of a DocType source; ingest then starts."""
    from frappe.utils import now_datetime
    from relay_core.business_access import document_name
    from relay_core.permissions import require_access
    document_name(name)
    require_access('Relay AI Knowledge Source', 'write')
    require_access(manage=True)
    doc = frappe.get_doc('Relay AI Knowledge Source', name)
    doc.check_permission('write')
    if doc.source_type != 'DocType':
        frappe.throw('Only DocType sources need approval')
    doc.current_hash = config_hash(doc, frappe.get_doc(BASE, doc.knowledge_base))
    doc.update(dict(approved_hash=doc.current_hash, approved_by=frappe.session.user, approved_on=now_datetime()))
    doc.flags.approving = True
    doc.save()
    return {'name': doc.name, 'approved_hash': doc.approved_hash}
