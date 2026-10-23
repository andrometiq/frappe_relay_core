import frappe
from frappe.model.document import Document


class RelayLegacyImport(Document):
    def validate(self):
        previous = self.get_doc_before_save()
        if previous and previous.status != 'Draft':
            for field in ('source_conversation', 'relay_contact', 'channel', 'source_bundle', 'source_site', 'source_channel', 'business_doctype', 'business_name', 'user_mapping', 'team_mapping', 'delta_since'):
                if self.get(field) != previous.get(field):
                    frappe.throw('An import mapping cannot change after it starts')
        if not getattr(frappe.flags, 'relay_legacy_import_write', False):
            for field in ('status', 'last_source', 'upper_source', 'imported', 'skipped', 'warnings', 'bundle_sha256', 'watermark', 'last_creation', 'upper_creation', 'source_metadata', 'reconcile_report'):
                expected = previous.get(field) if previous else ('Draft' if field == 'status' else 0 if field in ('imported','skipped') else None)
                if (self.get(field) or None) != (expected or None):
                    frappe.throw('Import progress is managed by the import service')
