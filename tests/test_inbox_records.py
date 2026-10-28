"""Inbox rows by business record: plain name search, readable records only, and the opaque cursor."""
import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict
from frappe.query_builder.utils import get_query_builder
from relay_core import inbox_records
from test_contact_primary import fake_frappe


class InboxRecordTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.qb = MagicMock(wraps=get_query_builder('mariadb'))
        self.fake.qb.DocType = get_query_builder('mariadb').DocType
        self.fake.db.escape = lambda value: "'" + value.replace("'", "''") + "'"
        self.enterContext(patch.object(inbox_records, 'frappe', self.fake))

    def test_every_word_must_be_in_the_name_in_any_order(self):
        values = inbox_records.search_values('Atal marketing')
        self.assertEqual({values['word0'], values['word1']}, {'%Atal%', '%marketing%'})
        self.assertNotIn('endpoint', values, 'A name never searches numbers')
        sql = self.fake.qb.from_('Relay Contact').select('name').where(inbox_records.contact_search('Atal marketing')).get_sql()
        self.assertIn("LIKE '%Atal%' AND", sql)
        self.assertIn("LIKE '%marketing%'", sql)
        self.assertNotIn('%A%t%a%l%', sql, 'Letters are not matched one by one, so "Patwa Sales" does not match "Atal"')

    def test_a_number_or_email_matches_the_chat_endpoints(self):
        self.assertEqual(inbox_records.search_values('+91 98765 43210')['endpoint'], '%919876543210%')
        self.assertEqual(inbox_records.search_values('ann@example.invalid')['endpoint'], '%ann@example.invalid%')
        sql = self.fake.qb.from_('Relay Contact').select('name').where(inbox_records.contact_search('98765')).get_sql()
        self.assertIn("`endpoint` LIKE '%98765%'", sql)

    def test_search_text_cannot_act_as_a_wildcard(self):
        self.assertEqual(inbox_records.search_values('50%_off')['word0'], '%50\\%\\_off%')

    def test_only_readable_business_types_are_listed_and_each_keeps_its_permission_query(self):
        self.fake.qb.get_query = lambda doctype, **kwargs: self.fake.qb.from_(doctype).select('name').where(
            self.fake.qb.DocType(doctype).owner == 'scope-' + doctype)
        values = {}
        with patch('relay_core.api.business_types', return_value=['Supplier']):
            condition = inbox_records.readable_condition(values, 'l')
        self.assertRegex(condition, r"l\.link_doctype=%\(qb\d+\)s AND l\.link_name IN \(SELECT")
        self.assertEqual(sorted(values.values()), ['Supplier', 'scope-Supplier'])
        self.assertNotIn('Customer', condition, 'A business type the user cannot read gives no rows')
        with patch('relay_core.api.business_types', return_value=[]):
            self.assertEqual(inbox_records.readable_condition({}, 'l'), '(0)')

    def test_user_values_are_bound_never_written_into_the_statement(self):
        attack = "x\\' OR 1=1 -- \\"
        self.fake.qb.get_query = lambda doctype, **kwargs: self.fake.qb.from_(doctype).select('name')
        contact = self.fake.qb.DocType('Relay Contact')
        state = self.fake.qb.DocType('Relay Conversation State')
        contacts = (self.fake.qb.from_(contact).select(contact.name, contact.contact, contact.display_name, contact.creation)
                    .where(contact.name.isin(self.fake.qb.from_(state).select(state.relay_contact).where(state.folder == attack)))
                    .where(contact.display_name.like('%50%')))
        self.fake.db.has_column.return_value = True
        self.fake.conf.db_type = 'mariadb'
        values = inbox_records.search_values(attack)
        from relay_core import inbox
        with patch('relay_core.api.business_types', return_value=['Customer']), patch.object(inbox, 'frappe', self.fake):
            unseen, sql = inbox_records.rows_sql(inbox_records.chats_query(contacts), values,
                                                 business_type='Customer', business_name=attack)
        statement = unseen + sql
        self.assertNotIn('OR 1=1', statement, 'No user value is written into the SQL text')
        self.assertNotIn('\\', statement)
        self.assertIn(attack, values.values(), 'The folder and the record name are bound values')
        self.assertIn('%50%', values.values())
        self.assertRegex(statement, r"`folder`=%\(qb\d+\)s")
        self.assertNotRegex(statement.replace('%%', ''), r"%(?!\(\w+\)s)", 'Every other percent sign is escaped')

    def test_a_record_missing_from_the_permission_list_is_never_titled(self):
        self.fake.get_meta.return_value.title_field = 'customer_name'
        self.fake.get_list.return_value = [_dict(name='CUST-1', customer_name='Atal Agencies')]
        titles = inbox_records.record_titles([('Customer', 'CUST-1'), ('Customer', 'CUST-2')])
        self.assertEqual(titles, {('Customer', 'CUST-1'): 'Atal Agencies'})
        self.assertEqual(self.fake.get_list.call_args.kwargs['filters'], {'name': ['in', ['CUST-1', 'CUST-2']]})

    def test_the_cursor_round_trips_and_rejects_tampering(self):
        self.fake.utils.get_datetime = lambda value: value
        row = _dict(search_rank=1, activity='2026-10-28 10:00:00.000001', doctype='Customer', record='CUST-1')
        self.assertEqual(inbox_records.decode_cursor(inbox_records.encode_cursor(row)),
                         {'cursor_rank': 1, 'cursor_activity': '2026-10-28 10:00:00.000001', 'cursor_doctype': 'Customer', 'cursor_record': 'CUST-1'})
        for value in ('RELAY-CON-1', '[9,"x","",""]', '[0,1,"",""]', '{}'):
            with self.assertRaises(ValueError):
                inbox_records.decode_cursor(value)

    def owners(self, totals, links, existing, primary=(None, None)):
        """The unstamped owner of chat P1, from link counts, enabled links and the records that still exist."""
        query = MagicMock()
        for method in ('select', 'where', 'groupby', 'distinct'):
            getattr(query, method).return_value = query
        query.run.side_effect = [totals, links]
        self.fake.qb = MagicMock()
        self.fake.qb.from_.return_value = query
        self.fake.get_all.side_effect = lambda doctype, filters, **kwargs: (
            ['Customer'] if doctype == 'Relay Contact Type' else [name for name in filters['name'][1] if (doctype, name) in existing])
        owner = inbox_records.unstamped_owners(['P1'])
        return owner(_dict(contact='P1', primary_doctype=primary[0], primary_name=primary[1]))

    def test_more_than_the_link_limit_gives_no_owner_as_in_the_thread(self):
        self.assertEqual(self.owners([('P1', 50)], [('P1', 'Customer', 'C1')], {('Customer', 'C1')}), ('Customer', 'C1'))
        self.assertIsNone(self.owners([('P1', 51)], [], set(), primary=('Customer', 'C1')),
                          'One enabled link plus 50 disabled-type links: the thread has no candidate, so no owner')
        self.assertEqual(self.fake.qb.from_.return_value.run.call_count, 1, 'Links are not read for a Contact over the limit')

    def test_a_link_whose_record_is_gone_is_not_a_candidate(self):
        links = [('P1', 'Customer', 'C1'), ('P1', 'Customer', 'gone')]
        self.assertEqual(self.owners([('P1', 2)], links, {('Customer', 'C1')}), ('Customer', 'C1'),
                         'One valid link plus one stale link: the valid one is the only candidate')
        self.assertEqual(self.owners([('P1', 2)], links, {('Customer', 'C1')}, primary=('Customer', 'gone')), ('Customer', 'C1'),
                         'A primary whose record is gone does not count')
        self.assertIsNone(self.owners([('P1', 3)], [*links, ('P1', 'Customer', 'C2')], {('Customer', 'C1'), ('Customer', 'C2')}))

    def test_the_owner_statement_caps_raw_links_and_needs_existing_records(self):
        self.fake.get_all.return_value = ['Customer']
        values = {}
        sql = inbox_records.owner_sql(values)
        self.assertIn("(SELECT COUNT(*) FROM `tabDynamic Link` x WHERE x.parent=f.contact AND x.parenttype='Contact' "
                      "AND x.parentfield='links')<=50", sql, 'The cap counts raw links of every type, before filtering')
        self.assertRegex(sql, r"x\.link_doctype=%\(qb\d+\)s AND x\.link_name IN \(SELECT `name` FROM `tabCustomer`\)")
        self.assertEqual(list(values.values()), ['Customer'])
        self.fake.get_all.return_value = []
        self.assertIn('AND (0))=1', inbox_records.owner_sql({}), 'No enabled type gives no candidate')


if __name__ == '__main__':
    unittest.main()
