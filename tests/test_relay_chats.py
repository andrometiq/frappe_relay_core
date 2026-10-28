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
        self.enterContext(patch('relay_core.inbox.directory_preview', return_value='Hello'))

    def get_value(self, doctype, filters, fields=None, **kwargs):
        if doctype == relay_chats.CHAT:
            return self.row
        return 'Atal Marketing' if fields == 'customer_name' else None

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
        self.fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: next(rows) if doctype == relay_chats.CHAT else 'Atal Marketing'
        relay_chats.on_message(message())
        insert = self.fake.db.bulk_insert.call_args
        self.assertEqual(insert.args[0], relay_chats.CHAT)
        self.assertTrue(insert.kwargs['ignore_duplicates'], 'A concurrent first message reuses the row')
        self.assertEqual(insert.args[2][0][5:], ('Customer', 'C1', 'Atal Marketing'))
        self.assertEqual(self.written(), {'last_message': 'RELAY-MSG-0000000005', 'last_message_at': AT, 'last_contact': 'R1',
                                          'last_channel': 'CH-1', 'last_message_preview': 'Hello', 'title': 'Atal Marketing',
                                          'unread_count': 1, 'is_unread': 1})

    def test_an_older_message_only_counts_as_unread_and_a_reply_counts_nothing(self):
        self.row = _dict(name='RC-1', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=2)
        relay_chats.on_message(message(at=AT - datetime.timedelta(minutes=5)))
        self.assertEqual(self.written(), {'unread_count': 3, 'is_unread': 1})
        self.fake.db.set_value.reset_mock()
        relay_chats.on_message(message(direction='Outgoing', at=AT - datetime.timedelta(minutes=5)))
        self.fake.db.set_value.assert_not_called()
        relay_chats.on_message(message(legacy_source='old', at=AT - datetime.timedelta(minutes=5)))
        self.fake.db.set_value.assert_not_called()

    def test_reading_to_the_end_clears_the_row_and_an_earlier_read_recounts(self):
        self.row = _dict(name='RC-1', last_message='RELAY-MSG-0000000009', last_message_at=AT, unread_count=3)
        with patch('relay_core.queue_counts.invalidate'):
            relay_chats.mark_read(('Customer', 'C1'), 'RELAY-MSG-0000000009')
            self.assertEqual(self.written(), {'unread_count': 0, 'is_unread': 0})
            self.fake.db.count.return_value = 1
            relay_chats.mark_read(('Customer', 'C1'), 'RELAY-MSG-0000000007')
        filters = self.fake.db.count.call_args.args[1]
        self.assertEqual((filters['business_doctype'], filters['business_name'], filters['name']), ('Customer', 'C1', ['>', 'RELAY-MSG-0000000007']))
        self.assertEqual(self.written(), {'unread_count': 1, 'is_unread': 1})
        self.fake.publish_realtime.assert_called_with('relay_changed', {'kind': 'chats'}, room=self.fake.realtime.get_doctype_room.return_value,
                                                      after_commit=True)

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

    def test_administrator_sees_every_chat_and_a_user_without_contacts_none(self):
        self.assertEqual(relay_chats.query('Administrator'), '')
        self.fake.has_permission.return_value = False
        self.assertEqual(relay_chats.query(), '1=0')

    def test_a_user_who_sees_every_team_gets_readable_records_and_visible_chats(self):
        with patch('relay_core.permissions.assignment_condition', return_value=''):
            condition = relay_chats.query()
        self.assertEqual(condition, "((records) OR (`tabRelay Chat`.business_doctype='Relay Contact' AND "
                                    "`tabRelay Chat`.business_name IN (SELECT name FROM `tabRelay Contact` WHERE scoped)))")

    def test_an_assigned_user_also_needs_a_visible_contact_of_the_record(self):
        with patch('relay_core.permissions.assignment_condition', return_value='(assigned)'):
            condition = relay_chats.query()
        self.assertIn('(records) AND EXISTS (SELECT 1 FROM `tabDynamic Link` l JOIN `tabRelay Contact`', condition)
        self.assertIn('l.link_doctype=`tabRelay Chat`.business_doctype AND l.link_name=`tabRelay Chat`.business_name AND (assigned)', condition)

    def test_one_row_is_checked_with_the_same_condition(self):
        self.fake.db.sql.return_value = []
        with patch.object(relay_chats, 'query', return_value='(scope)'):
            self.assertFalse(relay_chats.permission(_dict(name='RC-1')))
        self.assertEqual(self.fake.db.sql.call_args.args, ('SELECT 1 FROM `tabRelay Chat` WHERE name=%s AND (scope)', 'RC-1'))
        with patch.object(relay_chats, 'query', return_value=''):
            self.assertTrue(relay_chats.permission(_dict(name='RC-1')))


if __name__ == '__main__':
    unittest.main()
