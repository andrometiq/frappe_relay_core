"""Inbox rows by business record from Relay Chat: one permission-checked list query, plain search and a stable cursor."""
import datetime
import unittest
from unittest.mock import MagicMock, patch

import frappe.utils
from frappe import _dict
from frappe.query_builder.utils import get_query_builder
from relay_core import inbox_records
from test_contact_primary import fake_frappe

CHAT = 'Relay Chat'
AT = datetime.datetime(2026, 10, 28, 10, 0)


def chat(name, doctype='Customer', record='C1', at=AT, **values):
    return _dict(name=name, business_doctype=doctype, business_name=record, title=values.pop('title', record), last_contact='R1',
                 last_message_preview='Hi', last_message_at=at, last_channel='CH-1', unread_count=0, **values)


class InboxRecordTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.business_access.allowed_types', return_value={'Customer'}))
        self.enterContext(patch('relay_core.business_groups.title_field', return_value='customer_name'))
        self.fake = fake_frappe()
        self.fake.qb = MagicMock(wraps=get_query_builder('mariadb'))
        self.fake.qb.DocType = get_query_builder('mariadb').DocType
        self.fake.utils.get_datetime = frappe.utils.get_datetime
        self.fake.get_list.side_effect = self.get_list
        self.fake.get_all.return_value = []
        self.chats = []
        self.enterContext(patch.object(inbox_records, 'frappe', self.fake))
        self.enterContext(patch('relay_core.relay_chats.title', side_effect=lambda key:
            next((row.title for row in self.chats if (row.business_doctype, row.business_name) == key), key[1])))

    def get_list(self, doctype, **kwargs):
        if doctype == 'Relay Channel':
            return [('CH-1', 'WhatsApp')]
        return self.chats

    def chat_call(self):
        return [call for call in self.fake.get_list.call_args_list if call.args[0] == CHAT][-1]

    def test_every_word_must_be_in_the_name_in_any_order(self):
        values = inbox_records.search_values('Atal marketing')
        self.assertEqual({values['word0'], values['word1']}, {'%Atal%', '%marketing%'})
        self.assertNotIn('endpoint', values, 'A name never searches numbers')
        sql = self.fake.qb.from_('Relay Contact').select('name').where(inbox_records.contact_search('Atal marketing')).get_sql()
        self.assertIn("LIKE '%Atal%' AND", sql)
        self.assertIn("LIKE '%marketing%'", sql)

    def test_a_number_or_email_matches_the_chat_endpoints(self):
        self.assertEqual(inbox_records.search_values('+91 98765 43210')['endpoint'], '%919876543210%')
        self.assertEqual(inbox_records.search_values('ann@example.invalid')['endpoint'], '%ann@example.invalid%')
        sql = self.fake.qb.from_('Relay Contact').select('name').where(inbox_records.contact_search('98765')).get_sql()
        self.assertIn("`endpoint` LIKE '%98765%'", sql)

    def test_search_text_cannot_act_as_a_wildcard(self):
        self.assertEqual(inbox_records.search_values('50%_off')['word0'], '%50\\%\\_off%')
        self.assertIn("LIKE '%50\\%\\_off%'", inbox_records.search_filters('50%_off')[0].get_sql())

    def test_a_search_finds_business_records_by_title_or_name(self):
        self.chats = [chat('RC-1', title='Atal Marketing')]
        rows = inbox_records.page(query='Atal Marketing')['items']
        search = self.chat_call().kwargs['filters'][-1].get_sql(quote_char='`')
        self.assertIn('`customer_name` LIKE', search)
        self.assertIn("OR `business_name` LIKE '%Atal%Marketing%'", search)
        self.assertEqual([(row['kind'], row['doctype'], row['record'], row['title']) for row in rows],
                         [('business', 'Customer', 'C1', 'Atal Marketing')])

    def test_a_number_search_also_finds_chats_whose_last_writer_has_it(self):
        self.fake.qb.from_ = MagicMock()
        self.fake.qb.from_.return_value.select.return_value.where.return_value.limit.return_value.run.return_value = [('R7',)]
        self.assertEqual(inbox_records.search_filters('98765 43210')[-1], [CHAT, 'last_contact', 'in', ['R7']])

    def test_the_list_is_one_permission_checked_query_newest_first(self):
        inbox_records.page(mode='unread', channels=['CH-1'], business_type='Customer', business_name='C1', contacts=['R1'])
        call = self.chat_call()
        self.assertEqual(sum(1 for row in self.fake.get_list.call_args_list if row.args[0] == CHAT), 1)
        self.assertEqual(call.kwargs['order_by'], 'last_message_at desc, name desc')
        self.assertEqual(call.kwargs['limit_page_length'], inbox_records.PAGE + 1)
        self.assertEqual(call.kwargs['filters'], [[CHAT, 'is_unread', '=', 1], [CHAT, 'business_doctype', '=', 'Customer'],
                                                  [CHAT, 'business_name', '=', 'C1'], [CHAT, 'last_channel', 'in', ['CH-1']],
                                                  [CHAT, 'last_contact', 'in', ['R1']]])
        self.fake.get_all.assert_not_called()

    def test_tabs_and_record_filters(self):
        self.assertEqual(inbox_records.scope_filters('read'), [[CHAT, 'is_unread', '=', 0]])
        self.assertEqual(inbox_records.scope_filters('unlinked'), [[CHAT, 'business_doctype', '=', 'Relay Contact']])
        self.assertEqual(inbox_records.scope_filters('all', business_type='none'), [[CHAT, 'business_doctype', '=', 'Relay Contact']])
        self.assertEqual(inbox_records.scope_filters('all'), [])

    def test_the_cursor_neither_repeats_nor_skips_rows_that_share_a_time(self):
        self.chats = [chat(f'RC-{index}', record=f'C{index}', at=AT if index > 28 else AT + datetime.timedelta(minutes=40 - index))
                      for index in range(31)]
        result = inbox_records.page()
        self.assertEqual(len(result['items']), inbox_records.PAGE)
        at, names = inbox_records.decode_cursor(result['next']['after'])
        self.assertEqual((at, names), (AT, ['RC-29']))
        self.chats = []
        inbox_records.page(after=result['next']['after'])
        self.assertEqual(self.chat_call().kwargs['filters'], [[CHAT, 'last_message_at', '<=', AT], [CHAT, 'name', 'not in', ['RC-29']]])
        for tampered in ('[]', '["2026-10-28", []]', '["x", ["a"]]', 'not json', '[1, ["a"]]'):
            with self.subTest(tampered=tampered), self.assertRaises(ValueError):
                inbox_records.decode_cursor(tampered)

    def test_a_chat_without_a_record_opens_as_its_contact(self):
        self.chats = [chat('RC-1', doctype='Relay Contact', record='R9', title='+91 98765')]
        self.fake.get_all.side_effect = lambda doctype, **kwargs: (
            [('R9', 'CONTACT-9')] if doctype == 'Relay Contact' else [_dict(relay_contact='R9', starred=1, folder='F1')])
        with patch('relay_core.contacts.linked_contacts', return_value=set()), patch('relay_core.inbox.state_key', side_effect=str):
            row = inbox_records.page()['items'][0]
        self.assertEqual((row['kind'], row['name'], row['contact'], row['display_name']), ('contact', 'R9', 'CONTACT-9', '+91 98765'))
        self.assertEqual((row['unlinked'], row['starred'], row['folder'], row['provider']), (True, 1, 'F1', 'WhatsApp'))

    def test_counts_come_from_one_grouped_statement(self):
        self.chats = [_dict(business_doctype='Customer', total=5, unread=2, messages=7),
                      _dict(business_doctype='Relay Contact', total=3, unread=1, messages=1)]
        self.assertEqual(inbox_records.counts(['CH-1']), {'all': 8, 'unread': 3, 'read': 5, 'unlinked': 3, 'unread_messages': 8})
        call = self.chat_call()
        self.assertEqual(call.kwargs['group_by'], 'business_doctype')
        self.assertEqual(call.kwargs['filters'], [[CHAT, 'last_channel', 'in', ['CH-1']]])


if __name__ == '__main__':
    unittest.main()
