"""Contact edits keep endpoints, routing and message access in step."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from frappe import _dict
from relay_core import business_access, contact_lifecycle as lifecycle, identity


def person(name='Contact-A', phones=(), emails=()):
    return _dict(name=name, phone_nos=[_dict(phone=value) for value in phones],
                 email_ids=[_dict(email_id=value) for value in emails], mobile_no=None, phone=None, email_id=None)


class ContactNumberTests(unittest.TestCase):
    def test_international_and_national_formats_share_one_identity(self):
        with patch.object(identity, 'default_region', return_value='IN'):
            for value in ('+91 98765 43210', '+91-98765-43210', '(+91) 98765.43210', '0091 98765 43210',
                          '919876543210', '098765 43210', '9876543210'):
                with self.subTest(value=value):
                    self.assertEqual(identity.phone_number(value), '919876543210')

    def test_region_length_rules_decide_before_any_prefix(self):
        # An 11-digit Chinese mobile is national in CN; the old rule read it as +1 381...
        self.assertEqual(identity.phone_number('13812345678', 'CN'), '8613812345678')
        self.assertEqual(identity.phone_number('91234567', 'SG'), '6591234567')
        self.assertEqual(identity.phone_number('07911 123456', 'GB'), '447911123456')
        # Long numbers stored without + that are not valid in the region stay international.
        self.assertEqual(identity.phone_number('15550000001', 'IN'), '15550000001')
        self.assertIsNone(identity.phone_number('98765', 'IN'))

    def test_national_numbers_need_a_system_country(self):
        with patch.object(identity, 'default_region', return_value=''):
            self.assertIsNone(identity.phone_number('09876543210'))
            self.assertIsNone(identity.phone_number('9876543210'))
            self.assertEqual(identity.phone_number('+44 20 7946 0958'), '442079460958')

    def test_invalid_values_are_not_identities(self):
        for value in ('', None, 'call me', '+0123456789', '+1234', '+1234567890123456', '12345'):
            with self.subTest(value=value):
                self.assertIsNone(identity.phone_number(value, 'IN'))

    def test_contact_identities_cover_child_rows_and_primary_fields(self):
        doc = person(phones=['+91 98765 43210'], emails=['Ravi@Example.Invalid', 'not an email'])
        doc.mobile_no = '+91 91234 56789'
        self.assertEqual(identity.contact_identities(doc),
                         {'WhatsApp': {'919876543210', '919123456789'}, 'Email': {'ravi@example.invalid'}})


class ContactUpdateTests(unittest.TestCase):
    def setUp(self):
        self.endpoints = {'E-OLD': _dict(name='E-OLD', channel='CH-WA', endpoint='919876543210', verified=1),
                          'E-MAIL': _dict(name='E-MAIL', channel='CH-EMAIL', endpoint='ravi@example.invalid', verified=1)}
        self.inserted = []
        self.roles = ['Relay Communication Manager']

        def get_doc(value, name=None):
            if isinstance(value, dict):
                doc = _dict(value, save=Mock())
                self.inserted.append(doc)
                return doc
            return SimpleNamespace(**self.endpoints[name], save=Mock())

        providers = {'CH-WA': 'WhatsApp', 'CH-EMAIL': 'Email'}
        db = SimpleNamespace(get_value=lambda doctype, filters, field: (
            'RELAY-CON-A' if doctype == 'Relay Contact' else providers[filters]))
        self.fake = SimpleNamespace(db=db, get_doc=Mock(side_effect=get_doc), flags=SimpleNamespace(),
                                    get_all=Mock(return_value=list(self.endpoints.values())),
                                    get_roles=lambda: self.roles, cache=SimpleNamespace(lock=MagicMock()))
        self.enterContext(patch.object(lifecycle, 'frappe', self.fake))
        self.enterContext(patch.object(identity, 'default_region', return_value='IN'))
        self.verified = self.enterContext(patch.object(lifecycle, 'set_verified'))
        self.bindings = self.enterContext(patch.object(lifecycle, 'bindings', return_value=iter(())))

    def update(self, before, after):
        after.get_doc_before_save = lambda: before
        lifecycle.on_update(after)
        return [(getattr(call.args[0], 'name', None) or call.args[0]['endpoint'], call.args[1])
                for call in self.verified.call_args_list]

    def test_format_only_edit_and_added_values_keep_endpoints(self):
        self.assertEqual(self.update(person(phones=['+91 98765 43210']),
                                     person(phones=['098765 43210', '+91 91234 56789'])), [])
        self.fake.get_all.assert_not_called()

    def test_manager_number_change_disables_old_and_verifies_new(self):
        changes = self.update(person(phones=['+91 98765 43210'], emails=['ravi@example.invalid']),
                              person(phones=['+91 91234 56789'], emails=['ravi@example.invalid']))
        self.assertEqual(changes, [('E-OLD', 0), ('919123456789', 1)])
        self.assertEqual(self.inserted[0]['relay_contact'], 'RELAY-CON-A')
        self.assertEqual(self.inserted[0]['channel'], 'CH-WA')

    def test_plain_editor_only_disables(self):
        self.roles = ['Sales User']
        changes = self.update(person(phones=['+91 98765 43210'], emails=['ravi@example.invalid']),
                              person(phones=['+91 91234 56789']))
        self.assertEqual(changes, [('E-OLD', 0), ('E-MAIL', 0)])

    def test_shared_value_stays_with_existing_binding(self):
        self.bindings.return_value = iter([_dict(name='E-OTHER', relay_contact='RELAY-CON-B')])
        changes = self.update(person(phones=['+91 98765 43210']), person(phones=['+91 91234 56789']))
        self.assertEqual(changes, [('E-OLD', 0)])

    def test_contacts_without_relay_history_are_ignored(self):
        self.fake.db.get_value = lambda *args: None
        self.assertEqual(self.update(person(phones=['+91 98765 43210']), person()), [])


class ContactRemovalTests(unittest.TestCase):
    def setUp(self):
        def throw(message, exception=ValueError):
            raise exception(message)
        self.relay = {'Contact-A': 'RELAY-CON-A', 'Contact-B': 'RELAY-CON-B'}
        self.fake = SimpleNamespace(throw=throw, bold=str, LinkExistsError=PermissionError,
                                    db=SimpleNamespace(get_value=lambda doctype, filters, field: self.relay.get(filters['contact'])))
        self.enterContext(patch.object(lifecycle, 'frappe', self.fake))

    def test_delete_is_blocked_while_relay_history_exists(self):
        with self.assertRaises(PermissionError):
            lifecycle.on_trash(person('Contact-A'))
        lifecycle.on_trash(person('Contact-C'))

    def test_merge_is_blocked_only_when_both_contacts_have_relay_history(self):
        with self.assertRaises(ValueError):
            lifecycle.before_rename(person('Contact-A'), 'before_rename', 'Contact-A', 'Contact-B', True)
        lifecycle.before_rename(person('Contact-A'), 'before_rename', 'Contact-A', 'Contact-C', True)
        lifecycle.before_rename(person('Contact-A'), 'before_rename', 'Contact-A', 'Contact-B', False)


    def test_rename_rekeys_channel_preferences(self):
        from relay_core.channel_preferences import scope_key
        row = _dict(name='PREF-A', business_doctype='Customer', business_name='Sim Customer', endpoint='E-A')
        self.fake.get_all = Mock(return_value=[row])
        self.fake.db.set_value = Mock()
        lifecycle.after_rename(person('Contact-New'), 'after_rename', 'Contact-Old', 'Contact-New', False)
        values = self.fake.db.set_value.call_args.args[2]
        self.assertEqual(values['scope_key'], scope_key('Contact-New', 'Customer', 'Sim Customer'))
        self.assertNotEqual(values['scope_key'], scope_key('Contact-Old', 'Customer', 'Sim Customer'))


class LinkedBusinessAccessTests(unittest.TestCase):
    def test_removed_contact_link_ends_message_access(self):
        record = Mock(); record.has_permission.return_value = True
        fake = SimpleNamespace(session=SimpleNamespace(user='reader'), get_doc=Mock(return_value=record),
                               DoesNotExistError=LookupError)
        message = _dict(relay_contact='RELAY-CON-A', business_doctype='Customer', business_name='Sim Customer')
        with patch.object(business_access, 'frappe', fake), \
                patch.object(business_access, 'candidates', return_value=[('Customer', 'Sim Customer')]) as links:
            self.assertTrue(business_access.allowed(message))
            record.has_permission.assert_called_with('read', user=None)
            links.return_value = [('Supplier', 'Sim Supplier')]
            self.assertFalse(business_access.allowed(message))


if __name__ == '__main__':
    unittest.main()
