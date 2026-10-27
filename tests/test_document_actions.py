import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, module
from test_document_sends import stub_framework


class DocumentActionTests(unittest.TestCase):
    def setUp(self):
        self.f = stub_framework()
        self.sends = types.SimpleNamespace(contacts=Mock(return_value=['PERSON-A', 'PERSON-B']),
            targets=Mock(side_effect=lambda action, contact, channel: [(contact, 'EP-' + contact[-1])]),
            render_pdf=Mock(return_value=('Ledger.pdf', b'%PDF')),
            with_document=Mock(return_value=({'name': 'ledger', 'components': ['header']}, ('Ledger.pdf', b'%PDF', None))),
            send_template=Mock(return_value={'status': 'Submitted', 'action': 'A-1'}))
        self.actions = module('relay_core/document_actions.py', self.f, {'relay_core.document_sends': self.sends,
            'relay_core.permissions': types.SimpleNamespace(require_access=Mock())})
        self.actions.document_sends = self.sends
        self.action = Doc(name='Collection Follow-Up', enabled=1, document_type='Customer', business_field='name',
                          business_doctype='Customer', channel='CH-1', attachment_type='Report', roles=[])
        self.customer = Doc(doctype='Customer', name='CUST-A')
        self.f.get_doc.side_effect = lambda doctype, name: self.action if doctype == 'Relay Document Action' else self.customer
        self.actions.template_data = Mock(return_value={'name': 'ledger', 'language': 'en', 'components': []})
        self.actions.earlier_send = Mock(return_value=None)

    def test_role_and_doctype_limit_the_action(self):
        self.f.get_roles.return_value = ['Sales User']
        self.action.roles = [Doc(role='Accounts User')]
        with self.assertRaises(PermissionError): self.actions.load('Customer', 'CUST-A', 'Collection Follow-Up')
        self.action.roles = [Doc(role='Sales User')]
        self.assertEqual(self.actions.load('Customer', 'CUST-A', 'Collection Follow-Up')[2], 'CUST-A')
        with self.assertRaises(PermissionError): self.actions.load('Supplier', 'CUST-A', 'Collection Follow-Up')
        self.customer.denied = True
        with self.assertRaises(PermissionError): self.actions.load('Customer', 'CUST-A', 'Collection Follow-Up')

    def test_send_uploads_the_pdf_once_for_all_contacts(self):
        result = self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up', request_key='dialog-1')
        self.assertEqual([(row['contact'], row['endpoint'], row['status']) for row in result['results']],
                         [('PERSON-A', 'EP-A', 'Submitted'), ('PERSON-B', 'EP-B', 'Submitted')])
        self.sends.with_document.assert_called_once()
        keys = {call.args[3] for call in self.sends.send_template.call_args_list}
        self.assertEqual(len(keys), 2)
        self.assertEqual(self.sends.send_template.call_args.args[2], {'name': 'ledger', 'components': ['header']})

    def test_repeated_request_reuses_earlier_sends_without_upload(self):
        self.actions.earlier_send = Mock(return_value={'status': 'Submitted', 'action': 'A-0'})
        result = self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up', request_key='dialog-1')
        self.assertEqual({row['action'] for row in result['results']}, {'A-0'})
        self.sends.with_document.assert_not_called()
        self.sends.send_template.assert_not_called()

    def test_only_contacts_of_the_business_can_be_chosen(self):
        with self.assertRaises(PermissionError):
            self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up', contacts='["PERSON-X"]')
        result = self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up', contacts='["PERSON-B"]')
        self.assertEqual([row['contact'] for row in result['results']], ['PERSON-B'])
        with self.assertRaises(ValueError):
            self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up', request_key='bad key!')

    def test_failures_are_reported_per_contact(self):
        self.sends.targets = Mock(side_effect=[ValueError('Contact PERSON-A has no WhatsApp number'), [('PERSON-B', 'EP-B')]])
        result = self.actions.send('Customer', 'CUST-A', 'Collection Follow-Up')
        self.assertEqual(result['results'][0], {'contact': 'PERSON-A', 'status': 'Skipped', 'error': 'Contact PERSON-A has no WhatsApp number'})
        self.assertEqual(result['results'][1]['status'], 'Submitted')

    def test_disabled_action_can_be_saved_before_its_template_is_approved(self):
        approved = Mock(side_effect=ValueError('Choose an approved template'))
        events = types.SimpleNamespace(approved=approved, mapping=Mock(return_value=[]))
        self.f.get_meta.return_value = Doc(get_field=lambda key: None)
        self.sends.validate = Mock()
        with patch.dict(sys.modules, {'relay_core.business_events': events,
                                      'relay_core.business_references': types.SimpleNamespace(RELAY_DOCTYPES=())}):
            self.action.enabled = 0
            self.actions.validate_action(self.action)
            self.action.enabled = 1
            with self.assertRaisesRegex(ValueError, 'approved template'):
                self.actions.validate_action(self.action)

    def test_buttons_follow_roles(self):
        self.f.has_permission = Mock(return_value=True)
        self.f.cache.get_value.return_value = [
            {'name': 'Order PDF', 'document_type': 'YRP Sales Order', 'label': 'Send on WhatsApp', 'roles': []},
            {'name': 'Ledger', 'document_type': 'Customer', 'label': 'Send ledger', 'roles': ['Accounts User']}]
        self.f.get_roles.return_value = ['Sales User']
        self.assertEqual(self.actions.available(), {'YRP Sales Order': [{'name': 'Order PDF', 'label': 'Send on WhatsApp'}]})
        self.f.has_permission.return_value = False
        self.assertEqual(self.actions.available(), {})


if __name__ == '__main__':
    unittest.main()
