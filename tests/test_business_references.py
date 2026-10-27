"""Exercise Frappe's actual backlink checks without a site or database writes."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core.business_references import RELAY_DOCTYPES


class BusinessReferenceTests(unittest.TestCase):
    def test_all_relay_doctypes_are_exempt_and_business_names_are_plain_data(self):
        from relay_core import hooks
        for path in Path('relay_core/relay_core/doctype').glob('*/*.json'):
            meta = json.loads(path.read_text())
            self.assertIn(meta['name'], hooks.ignore_links_on_delete)
            # Cancel link checks block only on submitted rows, so Relay rows never block a cancel.
            self.assertFalse(meta.get('is_submittable'), meta['name'])
            for field in meta['fields']:
                if field['fieldname'] == 'business_name':
                    self.assertEqual(field['fieldtype'], 'Data')

    def test_cancel_of_other_documents_has_no_relay_hook(self):
        from relay_core import hooks
        self.assertNotIn('before_cancel', hooks.doc_events['*'])
        self.assertEqual(hooks.doc_events['*']['on_cancel'], 'relay_core.business_events.on_event')

    def test_framework_delete_and_cancel_leave_relay_rows_intact(self):
        delete = importlib.import_module('frappe.model.delete_doc')
        rename = importlib.import_module('frappe.model.rename_doc')
        # Includes old installed Dynamic Link metadata and custom Link fields on Relay records.
        fields = [_dict(parent=dt, fieldname='business_name', options='business_doctype', issingle=0)
                  for dt in RELAY_DOCTYPES]
        history = {dt: _dict(name='local-only-' + dt, business_name='local-only-customer') for dt in RELAY_DOCTYPES}
        original = {dt: dict(row) for dt, row in history.items()}
        fake = SimpleNamespace(get_hooks=lambda key: list(RELAY_DOCTYPES), db=Mock(),
                               get_meta=lambda dt: _dict(istable=0, issingle=0))
        fake.db.get_values.side_effect = lambda dt, *args, **kwargs: [_dict(history[dt], docstatus=0)]
        with patch.object(delete, 'frappe', fake), patch.object(rename, 'get_link_fields', return_value=fields), \
             patch.object(delete, 'get_dynamic_link_map', return_value={'Customer': fields}):
            doc = _dict(doctype='Customer', name='local-only-customer')
            delete.check_if_doc_is_linked(doc, 'Delete')
            delete.check_if_doc_is_dynamically_linked(doc, 'Delete')
            self.assertFalse(fake.db.mock_calls)
            self.assertEqual(delete.get_linked_docs(doc, 'Cancel'), [])
        self.assertEqual(history, original)
        self.assertIsNone(doc.get('ignore_linked_doctypes'))

    def test_unrelated_business_backlink_still_blocks(self):
        delete = importlib.import_module('frappe.model.delete_doc')
        rename = importlib.import_module('frappe.model.rename_doc')
        doc = _dict(doctype='Customer', name='local-only-customer')
        fake = SimpleNamespace(get_hooks=lambda key: list(RELAY_DOCTYPES), db=Mock(),
                               get_meta=lambda dt: _dict(istable=0, issingle=0))
        fake.db.get_values.return_value = [_dict(name='invoice', docstatus=1)]
        with patch.object(delete, 'frappe', fake), patch.object(rename, 'get_link_fields', return_value=[
                _dict(parent='Sales Invoice', fieldname='customer', issingle=0)]), \
             patch.object(delete, 'raise_link_exists_exception', side_effect=RuntimeError('Linked invoice')):
            for method in ('Delete', 'Cancel'):
                with self.assertRaisesRegex(RuntimeError, 'Linked invoice'):
                    delete.check_if_doc_is_linked(doc, method)


class BusinessReferenceSiteTests(unittest.TestCase):
    """Opt-in database lifecycle test; run only in an initialized local test site."""
    @classmethod
    def setUpClass(cls):
        import frappe
        if not getattr(frappe.local, 'site', None) or not frappe.conf.get('allow_tests'):
            raise unittest.SkipTest('Requires an initialized local site with allow_tests already enabled')
        if frappe.conf.get('db_host', '127.0.0.1') not in ('127.0.0.1', 'localhost'):
            raise unittest.SkipTest('Local database required')
        cls.business_type = 'Relay Reference Test Business'
        frappe.set_user('Administrator')
        if not frappe.db.exists('DocType', cls.business_type):
            frappe.get_doc(dict(doctype='DocType', name=cls.business_type, module='Relay Core',
                custom=1, is_submittable=1, allow_rename=1, autoname='field:title',
                fields=[dict(fieldname='title', label='Title', fieldtype='Data', reqd=1),
                        dict(fieldname='amount', label='Amount', fieldtype='Currency', reqd=1)],
                permissions=[dict(role='System Manager', read=1, write=1, create=1, delete=1,
                                  submit=1, cancel=1)])).insert()
        frappe.db.commit()  # Only the reusable, local test DocType survives rollback.

    def setUp(self):
        import frappe
        import uuid
        self.frappe = frappe
        frappe.db.savepoint('relay_reference_test')
        self.addCleanup(lambda: frappe.db.rollback(save_point='relay_reference_test'))
        self.enterContext(patch.object(frappe, 'enqueue'))
        self.enterContext(patch.object(frappe, 'sendmail', side_effect=AssertionError('No email in this test')))
        self.enterContext(patch('relay_core.hub.HubClient.call_tool', side_effect=AssertionError('No provider calls')))
        self.enterContext(patch.dict(frappe.conf, relay_automation_enabled=0))
        self.enterContext(patch.dict(frappe.flags, mute_emails=True))
        name = 'local-only-relay-reference-' + uuid.uuid4().hex
        self.business = frappe.get_doc(dict(doctype=self.business_type, title=name, amount=125)).insert()
        if not frappe.db.exists('Relay Contact Type', self.business_type):
            frappe.get_doc(dict(doctype='Relay Contact Type', business_doctype=self.business_type, enabled=1)).insert()
        person = frappe.get_doc(dict(doctype='Contact', first_name=name,
            links=[dict(link_doctype=self.business_type, link_name=self.business.name)])).insert()
        contact = frappe.get_doc(dict(doctype='Relay Contact', contact=person.name, display_name=name)).insert()
        channel = frappe.get_doc(dict(doctype='Relay Channel', channel='WhatsApp', account=name, enabled=0)).insert()
        self.message = frappe.get_doc(dict(doctype='Relay Message', relay_contact=contact.name,
            channel=channel.name, direction='Incoming', status='Delivered', content='Local order amount 125',
            business_doctype=self.business_type, business_name=self.business.name)).insert()
        self.ticket = frappe.get_doc(dict(doctype='Relay Ticket', subject=name,
            messages=[dict(message=self.message.name)])).insert()

    def assert_history(self, reference):
        self.message.reload()
        self.ticket.reload()
        self.assertEqual(self.message.business_name, reference)
        self.assertEqual(self.message.content, 'Local order amount 125')
        self.assertEqual(self.ticket.messages[0].message, self.message.name)
        self.message.content = 'Local order amount 125; retained history'
        self.message.save()

    def test_delete_keeps_messages_and_ticket(self):
        reference = self.business.name
        self.frappe.delete_doc(self.business_type, reference)
        self.assertFalse(self.frappe.db.exists(self.business_type, reference))
        self.assert_history(reference)

    def test_update_rename_and_cancel_keep_plain_reference(self):
        reference = self.business.name
        self.business.amount = 250
        self.business.save()
        self.business.rename(reference + '-renamed')
        self.business.submit()
        self.business.cancel()
        self.assertEqual(self.business.docstatus, 2)
        self.assert_history(reference)
