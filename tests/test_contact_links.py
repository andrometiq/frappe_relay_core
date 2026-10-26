"""Contact create, link and primary APIs, and the business type configuration API."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import business_access as access, business_types, contacts
from test_contact_primary import fake_frappe


class ContactApiTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe(flags=SimpleNamespace(), parse_json=Mock(side_effect=json.loads))
        self.enterContext(patch.object(contacts, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(contacts, 'require_access'))
        self.conversation = self.enterContext(patch.object(contacts, 'readable_contact'))
        self.records = {}
        self.inserted = []
        self.fake.db.exists.return_value = True

        def get_doc(value, name=None):
            if isinstance(value, dict):
                doc = Mock()
                doc.name = value['doctype'] + '-new'
                doc.insert.side_effect = lambda **kwargs: self.inserted.append((value, kwargs)) or doc
                return doc
            return self.records.setdefault((value, name), Mock())
        self.fake.get_doc.side_effect = get_doc
        self.channel = self.fake.get_doc('Relay Channel', 'RELAY-CH-0000000001')
        self.channel.channel, self.channel.enabled, self.channel.name = 'WhatsApp', 1, 'RELAY-CH-0000000001'
        self.enterContext(patch('relay_core.identity.bindings', return_value=iter(())))
        self.enterContext(patch('relay_core.identity.phone_number', return_value='919876543210'))

    def create(self, links=None):
        return contacts.create('Ravi', '98765 43210', 'RELAY-CH-0000000001', links)

    def test_create_makes_contact_relay_contact_and_verified_endpoint(self):
        result = self.create([{'doctype': 'Customer', 'name': 'C1'}])
        self.access.assert_called_once_with(manage=True)
        self.assertEqual(result, {'contact': 'Contact-new', 'relay_contact': 'Relay Contact-new',
                                  'endpoint': 'Relay Contact Endpoint-new'})
        person, relay, endpoint = (row[0] for row in self.inserted)
        self.assertEqual(person['phone_nos'], [{'phone': '+919876543210', 'is_primary_mobile_no': 1}])
        self.assertEqual(person['links'], [{'link_doctype': 'Customer', 'link_name': 'C1'}])
        self.assertEqual(self.inserted[0][1], {}, 'Contact creation keeps Frappe permission checks')
        self.assertEqual((relay['contact'], relay['display_name']), ('Contact-new', 'Ravi'))
        self.assertEqual((endpoint['endpoint'], endpoint['verified']), ('919876543210', 1))
        self.records[('Customer', 'C1')].check_permission.assert_called_once_with('read')
        self.assertFalse(self.fake.flags.relay_endpoint_enrollment)

    def test_create_denies_users_unreadable_records_and_known_numbers(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.create()
        self.access.side_effect = None
        self.fake.get_doc('Customer', 'private').check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.create([{'doctype': 'Customer', 'name': 'private'}])
        with patch('relay_core.identity.bindings', return_value=iter([_dict(name='existing')])), self.assertRaises(KeyError):
            self.create()
        self.fake.db.exists.return_value = False
        with self.assertRaises(PermissionError):
            self.create([{'doctype': 'ToDo', 'name': 'T1'}])
        self.assertEqual(self.inserted, [])

    def test_set_links_replaces_readable_links_and_keeps_the_rest(self):
        person = self.fake.get_doc('Contact', 'P1')
        person.name = 'P1'
        person.links = [_dict(link_doctype='Customer', link_name='old'), _dict(link_doctype='Customer', link_name='private'),
                        _dict(link_doctype='Address', link_name='A1')]
        self.fake.get_all.return_value = ['Customer', 'Supplier']
        self.fake.get_doc('Customer', 'private').has_permission.return_value = False
        with patch.object(contacts, 'summary', return_value='summary'):
            self.assertEqual(contacts.set_links('P1', '[{"doctype": "Supplier", "name": "S1"}]'), 'summary')
        person.check_permission.assert_called_once_with('write')
        self.fake.parse_json.assert_called_once()
        rows = person.set.call_args.args[1]
        self.assertEqual({(row['link_doctype'], row['link_name']) for row in rows},
                         {('Customer', 'private'), ('Address', 'A1'), ('Supplier', 'S1')})
        person.save.assert_called_once_with()

    def test_set_links_denies_without_contact_write_or_record_read(self):
        person = self.fake.get_doc('Contact', 'P1')
        person.check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            contacts.set_links('P1', [{'doctype': 'Supplier', 'name': 'S1'}])
        person.check_permission.side_effect = None
        self.fake.get_doc('Supplier', 'S1').check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            contacts.set_links('P1', [{'doctype': 'Supplier', 'name': 'S1'}])
        person.save.assert_not_called()

    def test_set_primary_marks_only_a_linked_readable_record(self):
        self.fake.db.get_value.return_value = 'RELAY-CON-0000000001'
        relay = self.fake.get_doc('Relay Contact', 'RELAY-CON-0000000001')
        with patch.object(contacts, 'summary', return_value='summary'), \
                patch.object(access, 'candidates', return_value=[('Customer', 'C1'), ('Supplier', 'S1')]):
            self.assertEqual(contacts.set_primary('P1', 'Supplier', 'S1'), 'summary')
            self.assertEqual((relay.primary_doctype, relay.primary_name), ('Supplier', 'S1'))
            relay.save.assert_called_once_with(ignore_permissions=True)
            with self.assertRaises(ValueError):
                contacts.set_primary('P1', 'Customer', 'C2')
            self.fake.get_doc('Customer', 'C1').check_permission.side_effect = PermissionError
            with self.assertRaises(PermissionError):
                contacts.set_primary('P1', 'Customer', 'C1')
            contacts.set_primary('P1')
            self.assertEqual((relay.primary_doctype, relay.primary_name), (None, None))

    def test_set_primary_denies_without_contact_write(self):
        self.fake.get_doc('Contact', 'P1').check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            contacts.set_primary('P1', 'Customer', 'C1')
        self.fake.get_doc('Relay Contact', 'RELAY-CON-0000000001').save.assert_not_called()


    def test_set_primary_denies_users_outside_the_conversation(self):
        self.fake.db.get_value.return_value = 'RELAY-CON-0000000001'
        self.conversation.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            contacts.set_primary('P1', 'Customer', 'C1')
        self.conversation.assert_called_once_with('RELAY-CON-0000000001')
        self.fake.get_doc('Relay Contact', 'RELAY-CON-0000000001').save.assert_not_called()


class BusinessTypeApiTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.enterContext(patch.object(business_types, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(business_types, 'require_access'))

    def test_list_shows_readable_types_and_disabled_only_to_system_managers(self):
        self.fake.get_all.return_value = [_dict(business_doctype='Customer'), _dict(business_doctype='Supplier')]
        self.fake.has_permission.side_effect = lambda doctype, ptype: doctype == 'Customer'
        self.fake.get_roles.return_value = ['Relay Communication User']
        self.assertEqual(business_types.list_types(), [_dict(business_doctype='Customer')])
        self.assertEqual(self.fake.get_all.call_args.kwargs['filters'], {'enabled': 1})
        self.fake.get_roles.return_value = ['System Manager']
        business_types.list_types()
        self.assertEqual(self.fake.get_all.call_args.kwargs['filters'], {})

    def test_save_is_system_manager_only_and_needs_a_readable_doctype(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            business_types.save('Customer')
        self.access.assert_called_with(configure=True)
        self.access.side_effect = None
        self.fake.get_meta.return_value = _dict(istable=0, issingle=0)
        self.fake.has_permission.return_value = False
        with self.assertRaises(PermissionError):
            business_types.save('Customer')
        self.fake.get_meta.return_value = _dict(istable=1, issingle=0)
        with self.assertRaises(ValueError):
            business_types.save('Sales Invoice Item')
        self.fake.new_doc.return_value.save.assert_not_called()

    def test_save_creates_or_updates_one_type(self):
        self.fake.get_meta.return_value = _dict(istable=0, issingle=0)
        self.fake.has_permission.return_value = True
        self.fake.db.exists.side_effect = lambda doctype, name: doctype == 'DocType'
        doc = self.fake.new_doc.return_value
        doc.get.side_effect = lambda field: getattr(doc, field)
        result = business_types.save('Customer', '0', ' Customers ', 'customer_group')
        self.assertEqual((doc.business_doctype, doc.enabled, doc.label, doc.grouping_field),
                         ('Customer', 0, 'Customers', 'customer_group'))
        doc.save.assert_called_once_with()
        self.assertEqual(result['business_doctype'], 'Customer')
        with self.assertRaises(ValueError):
            business_types.save('Customer', 'yes')


if __name__ == '__main__':
    unittest.main()
