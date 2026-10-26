"""Primary business link and one conversation per contact."""
import unittest
from unittest.mock import MagicMock, Mock, patch

from frappe import _dict
from relay_core import business_access as access, business_inbox


def fake_frappe(**values):
    fake = MagicMock()
    fake.session.user = 'reader'
    fake.DoesNotExistError = LookupError
    fake.PermissionError = PermissionError
    fake.DuplicateEntryError = KeyError
    fake.throw.side_effect = lambda message, error=ValueError: (_ for _ in ()).throw(error(message))
    for key, value in values.items():
        setattr(fake, key, value)
    return fake


class PrimaryLinkTests(unittest.TestCase):
    def setUp(self):
        self.marked = None
        self.fake = fake_frappe()
        self.fake.db.get_value.side_effect = lambda *args, **kwargs: self.marked
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.links = self.enterContext(patch.object(access, 'candidates', return_value=[]))

    def test_primary_with_no_one_or_several_links(self):
        self.assertIsNone(access.primary('contact'))
        self.links.return_value = [('Customer', 'C1')]
        self.assertEqual(access.primary('contact'), ('Customer', 'C1'), 'One link is implicitly primary')
        self.links.return_value = [('Customer', 'C1'), ('Supplier', 'S1')]
        self.assertIsNone(access.primary('contact'))
        self.marked = ('Supplier', 'S1')
        self.assertEqual(access.primary('contact'), ('Supplier', 'S1'))
        self.marked = ('Supplier', 'removed')
        self.assertIsNone(access.primary('contact'), 'A primary without its Contact link does not count')

    def test_reference_and_default_choice_use_the_primary(self):
        self.links.return_value = [('Customer', 'C1'), ('Supplier', 'S1')]
        self.marked = ('Supplier', 'S1')
        self.assertEqual(access.reference(_dict(relay_contact='contact')), ('Supplier', 'S1'))
        self.assertEqual(access.reference(_dict(relay_contact='contact', business_doctype='Customer', business_name='C1')),
                         ('Customer', 'C1'))
        self.assertIsNone(access.reference(_dict(relay_contact='contact', legacy_triage=1)))
        self.assertEqual(access.choose_business('contact'), ('Supplier', 'S1'))
        self.marked = None
        with self.assertRaises(ValueError):
            access.choose_business('contact')

    def test_stale_primary_is_cleared_and_a_valid_one_is_kept(self):
        self.links.return_value = [('Customer', 'C1')]
        self.marked = ('Customer', 'C1')
        access.drop_stale_primary('contact')
        self.fake.db.set_value.assert_not_called()
        self.marked = ('Supplier', 'S1')
        access.drop_stale_primary('contact')
        self.fake.db.set_value.assert_called_once_with('Relay Contact', 'contact',
                                                       {'primary_doctype': None, 'primary_name': None})

    def test_header_record_needs_read_permission(self):
        self.links.return_value = [('Customer', 'C1')]
        record = Mock(meta=_dict(title_field='customer_name'))
        record.get.return_value = 'Primary customer'
        self.fake.get_doc.return_value = record
        self.assertEqual(access.primary_record('contact'), {'doctype': 'Customer', 'name': 'C1', 'title': 'Primary customer'})
        record.has_permission.return_value = False
        self.assertIsNone(access.primary_record('contact'))

    def test_legacy_query_resolves_to_the_only_or_primary_link(self):
        self.fake.get_all.return_value = ['Customer']
        self.fake.has_permission.return_value = True
        self.fake.qb.get_query.return_value.get_sql.return_value = 'SELECT name FROM `tabCustomer`'
        self.fake.db.escape = lambda value: f"'{value}'"
        condition = access.query_condition()
        self.assertIn("OR (r.primary_doctype='Customer' AND r.primary_name=l.link_name)", condition)
        self.assertEqual(condition.count('('), condition.count(')'))


class ConversationAccessTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.allowed = self.enterContext(patch.object(access, 'allowed', return_value=False))
        self.contact = self.fake.get_doc.return_value

    def test_contact_conversation_shows_every_message_to_its_readers(self):
        message = _dict(doctype='Relay Message', relay_contact='contact', business_doctype='Supplier', business_name='S1')
        self.contact.has_permission.return_value = True
        self.assertTrue(access.message_allowed(message, user='reader'))
        self.fake.get_doc.assert_called_with('Relay Contact', 'contact')
        self.contact.has_permission.assert_called_with('read', user='reader')

    def test_contact_conversation_denies_non_readers_and_triage(self):
        message = _dict(doctype='Relay Message', relay_contact='contact')
        self.contact.has_permission.return_value = False
        self.assertFalse(access.message_allowed(message, user='reader'))
        self.contact.has_permission.return_value = True
        self.assertFalse(access.message_allowed(_dict(message, legacy_triage=1), user='reader'))
        self.fake.get_doc.side_effect = LookupError
        self.assertFalse(access.message_allowed(message, user='reader'))

    def test_query_adds_the_readable_contact_scope(self):
        self.fake.has_permission.return_value = True
        self.fake.qb.get_query.return_value.get_sql.return_value = 'SELECT name FROM `tabRelay Contact`'
        with patch.object(access, 'query_condition', return_value='business'):
            condition = access.message_condition('reader')
        self.assertEqual(condition, "(business OR (COALESCE(`tabRelay Message`.legacy_triage,0)=0 AND "
                                    "`tabRelay Message`.relay_contact IN (SELECT name FROM `tabRelay Contact`)))")
        self.fake.has_permission.return_value = False
        with patch.object(access, 'query_condition', return_value='business'):
            self.assertEqual(access.message_condition('reader'), 'business')
        with patch.object(access, 'query_condition', return_value=''):
            self.assertEqual(access.message_condition('Administrator'), '')

    def test_business_timeline_takes_unstamped_messages_only_from_resolved_contacts(self):
        linked = Mock()
        linked.limit.return_value.run.return_value = [('A',), ('B',)]
        resolved = {'A': ('Customer', 'C1'), 'B': ('Customer', 'C2')}
        with patch.object(access, 'primary', side_effect=lambda contact: resolved[contact]):
            self.assertEqual(business_inbox.resolved_contacts('Customer', 'C1', linked), ['A'])


if __name__ == '__main__':
    unittest.main()
