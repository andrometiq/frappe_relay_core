"""Relay Chat rows: the message hook keeps one row per record, reads lower the shared unread count, and the
permission query mirrors record and contact access."""
import datetime
import unittest
from unittest.mock import patch

import frappe.utils
from frappe import _dict
from relay_core import relay_chats
from test_contact_primary import fake_frappe

AT = datetime.datetime(2026, 10, 28, 10, 0)


def message(name='RELAY-MSG-0000000005', direction='Incoming', at=AT, **values):
    return _dict(name=name, relay_contact='R1', channel='CH-1', direction=direction, sent_at=at, creation=at,
                 business_doctype=values.pop('business_doctype', 'Customer'), business_name=values.pop('business_name', 'C1'), **values)


class RelayChatTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.utils.get_datetime = frappe.utils.get_datetime
        self.fake.get_meta.return_value.title_field = 'customer_name'
        self.row = None
        self.fake.db.get_value.side_effect = self.get_value
        self.enterContext(patch.object(relay_chats, 'frappe', self.fake))
        self.enterContext(patch('relay_core.business_groups.title_field', return_value='customer_name'))
        self.enterContext(patch('relay_core.inbox.directory_preview', return_value='Hello'))

    def get_value(self, doctype, filters, fields=None, **kwargs):
        if doctype == relay_chats.CHAT:
            return self.row
        return 'Kestrel Traders' if fields == 'customer_name' else None

    def written(self):
        return self.fake.db.set_value.call_args.args[2]

    def test_a_message_belongs_to_its_record_else_to_its_chat_and_triage_to_none(self):
        self.assertEqual(relay_chats.key_of(message()), ('Customer', 'C1'))
        unstamped = message(business_doctype='', business_name=None)
        self.assertEqual(relay_chats.key_of(unstamped, {'R1': None}), ('Relay Contact', 'R1'))
        self.assertEqual(relay_chats.key_of(unstamped, {'R1': ('Customer', 'C9')}), ('Customer', 'C9'),
                         'Unstamped messages belong to the record whose thread shows them')
        with patch('relay_core.business_access.primary', return_value=None) as primary:
            self.assertEqual(relay_chats.key_of(unstamped), ('Relay Contact', 'R1'))
        primary.assert_called_once_with('R1')
        self.assertIsNone(relay_chats.key_of(message(legacy_triage=1)))

    def test_the_first_message_creates_the_row_once_even_when_two_arrive_together(self):
        rows = iter([None, _dict(name='RC-1', last_message=None, last_message_at=None, unread_count=0)])
        self.fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: next(rows) if doctype == relay_chats.CHAT else 'Kestrel Traders'
        relay_chats.on_message(message())
        insert = self.fake.db.bulk_insert.call_args
        self.assertEqual(insert.args[0], relay_chats.CHAT)
        self.assertTrue(insert.kwargs['ignore_duplicates'], 'A concurrent first message reuses the row')
        self.assertEqual(insert.args[2][0][5:], ('Customer', 'C1', 'Kestrel Traders'))
        self.assertEqual(self.written(), {'last_message': 'RELAY-MSG-0000000005', 'last_message_at': AT, 'last_contact': 'R1',
                                          'last_channel': 'CH-1', 'last_message_preview': 'Hello', 'title': 'Kestrel Traders',
                                          'unread_count': 1, 'is_unread': 1})

    def test_an_older_message_only_counts_as_unread_and_a_reply_recounts_its_chat(self):
        self.row = _dict(name='RC-1', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=2)
        relay_chats.on_message(message(at=AT - datetime.timedelta(minutes=5)))
        self.assertEqual(self.written(), {'unread_count': 3, 'is_unread': 1})
        self.fake.db.set_value.reset_mock()
        with patch.object(relay_chats, 'thread_unread', return_value={('R1', 'CH-2', '922'): (1, 'M-7', 'M-7')}) as unread:
            relay_chats.on_message(message(direction='Outgoing', at=AT - datetime.timedelta(minutes=5)))
        unread.assert_called_once_with(('Customer', 'C1'))
        self.assertEqual(self.written(), {'unread_count': 1, 'is_unread': 1}, 'A reply answers only its own thread')
        self.fake.db.set_value.reset_mock()
        relay_chats.on_message(message(legacy_source='old', at=AT - datetime.timedelta(minutes=5)))
        self.fake.db.set_value.assert_not_called()

    def test_a_read_recounts_every_thread_and_a_full_read_reads_each_unread_thread(self):
        self.row = _dict(name='RC-1', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=3)
        threads = {('R1', 'CH-1', '911'): (2, 'M-5', 'M-8'), ('R2', 'CH-2', 'b@x.invalid'): (1, 'M-6', 'M-6')}
        with patch('relay_core.queue_counts.invalidate'), patch.object(relay_chats, 'thread_unread', return_value=threads), \
                patch('relay_core.message_reads.insert_reads') as reads, patch('relay_core.realtime.readers_changed') as published:
            relay_chats.mark_read(('Customer', 'C1'))
            self.fake.db.set_value.assert_not_called()
            reads.assert_not_called()
            self.row.unread_count = 4
            relay_chats.mark_read(('Customer', 'C1'))
            self.assertEqual(self.written(), {'unread_count': 3, 'is_unread': 1})
            published.assert_called_with({'kind': 'chats'}, 'Relay Message')
            relay_chats.mark_read(('Customer', 'C1'), everything=True)
        reads.assert_called_once_with([('R1', 'M-8'), ('R2', 'M-6')])

    def test_one_sql_rule_counts_each_thread_after_its_own_read_or_reply(self):
        self.fake.db.sql.return_value = [('R1', 'CH-1', '911', 2, 'M-5', 'M-8')]
        self.assertEqual(relay_chats.thread_unread(('Customer', 'C1')), {('R1', 'CH-1', '911'): (2, 'M-5', 'M-8')})
        self.assertEqual(relay_chats.unread_total(('Customer', 'C1')), 2)
        statement, values = self.fake.db.sql.call_args.args
        self.assertEqual(values, {'doctype': 'Customer', 'name': 'C1'})
        self.assertIn("m.direction='Incoming'", statement)
        self.assertIn("x.direction='Outgoing' OR x.name IN (SELECT message FROM `tabRelay Message Read`)", statement)
        self.assertIn("c.thread_endpoint=COALESCE(m.sender_endpoint, '')", statement, 'The read position is per thread')
        self.assertIn('m.name>COALESCE(c.seen', statement)
        self.assertNotIn('LIMIT', statement.upper(), 'No scan window can drop an older unread thread')
        relay_chats.thread_unread(('Relay Contact', 'R1'))
        self.assertEqual(self.fake.db.sql.call_args.args[1], {'contact': 'R1'})
        with patch.object(relay_chats, 'unread_threads', return_value=[('Customer', 'C1', 'R1', 'CH-1', '911', 2, 'M-5', 'M-8'),
                                                                     ('Relay Contact', 'R7', 'R7', 'CH-1', '933', 1, 'M-2', 'M-2'),
                                                                     ('Relay Contact', 'R9', 'R9', 'CH-1', '944', 3, 'M-3', 'M-4')]) as shared:
            self.assertEqual(relay_chats.unread_counts({'R7': ('Customer', 'C1')}), {('Customer', 'C1'): 3, ('Relay Contact', 'R9'): 3},
                             'A rebuild uses the same rule and adds each thread to its chat')
        self.assertEqual(len(shared.call_args.kwargs['key']), 2)

    def test_the_unread_threads_of_many_chats_come_from_one_query(self):
        self.fake.db.sql.return_value = [('Customer', 'C1', 'R1', 'CH-1', '911', 2, 'M-5', 'M-8'),
                                          ('Relay Contact', 'R7', 'R7', 'CH-2', '933', 1, 'M-2', 'M-2')]
        result = relay_chats.unread_by_chat([('Customer', 'C1'), ('Relay Contact', 'R7')])
        self.assertEqual(result, {('Customer', 'C1'): {('R1', 'CH-1', '911'): (2, 'M-5', 'M-8')},
                                  ('Relay Contact', 'R7'): {('R7', 'CH-2', '933'): (1, 'M-2', 'M-2')}})
        self.assertEqual(self.fake.db.sql.call_count, 1)
        statement, values = self.fake.db.sql.call_args.args
        self.assertEqual(values, {'doctype_0': 'Customer', 'name_0': 'C1', 'contact_1': 'R7'})
        self.assertIn('(m.business_doctype=%(doctype_0)s AND m.business_name=%(name_0)s) OR (m.relay_contact=%(contact_1)s', statement)
        self.assertIn("IF(COALESCE(m.business_name, '')='', 'Relay Contact', m.business_doctype)", statement)
        self.fake.db.sql.reset_mock()
        self.assertEqual(relay_chats.unread_by_chat([]), {})
        self.fake.db.sql.assert_not_called()

    def test_a_read_that_lowers_nothing_writes_nothing(self):
        self.row = _dict(name='RC-1', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=0)
        relay_chats.mark_read(('Customer', 'C1'))
        self.fake.db.set_value.assert_not_called()
        self.fake.publish_realtime.assert_not_called()

    def test_linking_a_chat_moves_its_row_into_the_record(self):
        old = _dict(name='RC-OLD', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=2)
        record = _dict(name='RC-1', last_message='RELAY-MSG-0000000001', last_message_at=AT - datetime.timedelta(days=1), unread_count=1)
        rows = iter([old, record])
        self.fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: next(rows) if doctype == relay_chats.CHAT else None
        self.fake.get_doc.return_value = message(name='RELAY-MSG-0000000009')
        relay_chats.merge('R1', ('Customer', 'C1'))
        self.assertEqual(self.fake.db.set_value.call_args.args[1], 'RC-1')
        self.assertEqual({key: self.written()[key] for key in ('last_message', 'unread_count', 'is_unread')},
                         {'last_message': 'RELAY-MSG-0000000009', 'unread_count': 3, 'is_unread': 1})
        self.fake.db.delete.assert_called_once_with(relay_chats.CHAT, {'name': 'RC-OLD'})


class RelayChatPermissionTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.session.user = 'agent@example.invalid'
        self.fake.has_permission.return_value = True
        self.fake.qb.get_query.return_value.get_sql.return_value = 'SELECT name FROM `tabRelay Contact` WHERE scoped'
        self.enterContext(patch.object(relay_chats, 'frappe', self.fake))
        self.enterContext(patch('relay_core.business_access.explicit_condition', return_value='(records)'))
        self.role = self.enterContext(patch('relay_core.business_access.relay_user', return_value=True))

    def test_administrator_sees_every_chat_and_a_user_without_contacts_none(self):
        self.assertIn('(records)', relay_chats.query('Administrator'))
        self.role.return_value = False
        self.assertEqual(relay_chats.query(), '1=0')

    def test_a_user_who_sees_every_team_gets_readable_records_and_visible_chats(self):
        with patch('relay_core.permissions.assignment_condition', return_value=''):
            condition = relay_chats.query()
        self.assertEqual(condition, "((records) OR (`tabRelay Chat`.business_doctype='Relay Contact' AND "
                                    "`tabRelay Chat`.business_name IN (SELECT name FROM `tabRelay Contact` WHERE scoped)))")

    def test_business_records_do_not_need_team_assignment(self):
        condition = relay_chats.query()
        self.assertIn('(records)', condition)
        self.assertNotIn('Relay Conversation Assignment', condition)
        self.assertNotIn('Relay Team', condition)

    def test_one_row_is_checked_with_the_same_condition(self):
        self.fake.db.sql.return_value = []
        with patch.object(relay_chats, 'query', return_value='(scope)'):
            self.assertFalse(relay_chats.permission(_dict(name='RC-1')))
        self.assertEqual(self.fake.db.sql.call_args.args, ('SELECT 1 FROM `tabRelay Chat` WHERE name=%s AND (scope)', 'RC-1'))
        with patch.object(relay_chats, 'query', return_value=''):
            self.assertTrue(relay_chats.permission(_dict(name='RC-1')))


if __name__ == '__main__':
    unittest.main()
