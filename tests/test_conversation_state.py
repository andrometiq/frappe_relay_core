"""Per-user inbox state writes: fresh snapshot, one quiet deadlock retry, no write when nothing changed, no series."""
import datetime
import json
import unittest
from unittest.mock import Mock, patch

from frappe import _dict

from relay_core import conversation_state as state, message_reads

NOW = datetime.datetime(2026, 10, 28, 12, 0, 0)


class Deadlock(Exception):
    pass


def fake_site(row=None):
    site = Mock(QueryDeadlockError=Deadlock)
    site.session.user = 'reader@example.invalid'
    site.utils.now_datetime.return_value = NOW
    site.utils.get_datetime.side_effect = lambda value: value
    site.generate_hash.side_effect = iter(f'hash{i}' for i in range(100))
    site.db.get_value.side_effect = lambda doctype, name, fields=None, **kw: (
        'STATE-1' if fields == 'name' else _dict(row or {}))
    return site


class FreshWriteTests(unittest.TestCase):
    def test_write_starts_a_new_transaction_and_retries_one_deadlock(self):
        site = fake_site()
        write = Mock(side_effect=[Deadlock(), 'done'])
        with patch.object(state, 'frappe', site):
            self.assertEqual(state.fresh_write(write), 'done')
        self.assertEqual(write.call_count, 2)
        self.assertEqual(site.db.commit.call_count, 2)
        site.db.rollback.assert_called_once_with()

    def test_a_second_deadlock_raises_after_rolling_back(self):
        site = fake_site()
        with patch.object(state, 'frappe', site):
            with self.assertRaises(state.StateWriteFailed): state.fresh_write(Mock(side_effect=Deadlock()))
        self.assertEqual(site.db.rollback.call_count, 2)

    def test_other_errors_are_raised(self):
        with patch.object(state, 'frappe', fake_site()):
            with self.assertRaises(ValueError): state.fresh_write(Mock(side_effect=ValueError('bad')))


class SaveStateTests(unittest.TestCase):
    def save(self, row, values):
        site = fake_site(row)
        with patch.object(state, 'frappe', site), patch('relay_core.realtime.contact_changed') as changed, \
                patch('relay_core.inbox.state_key', return_value='key'):
            result = state.save_state('RELAY-CON-0000000001', values)
        return site, result, changed

    def test_unchanged_recent_state_is_not_written(self):
        site, result, changed = self.save(dict(last_read='RELAY-MSG-0000000005', starred=1, folder=None,
                                               last_seen=NOW - datetime.timedelta(seconds=5)),
                                          {'last_read': 'RELAY-MSG-0000000005', 'starred': 1})
        self.assertEqual(result, {})
        site.db.set_value.assert_not_called()
        changed.assert_not_called()

    def test_presence_is_refreshed_without_touching_modified(self):
        site, result, _ = self.save(dict(last_read=None, starred=0, folder=None,
                                         last_seen=NOW - datetime.timedelta(minutes=1)), {})
        site.db.set_value.assert_called_once_with(state.STATE, 'STATE-1', {'last_seen': NOW}, update_modified=False)

    def test_cursor_moves_forward_only_and_announces_a_change(self):
        row = dict(last_read='RELAY-MSG-0000000005', starred=0, folder=None, last_seen=NOW)
        site, result, changed = self.save(row, {'last_read': 'RELAY-MSG-0000000003', 'starred': 1})
        self.assertEqual(result, {'starred': 1})
        changed.assert_not_called()
        site, result, changed = self.save(row, {'last_read': 'RELAY-MSG-0000000009'})
        self.assertEqual(result, {'last_read': 'RELAY-MSG-0000000009'})
        site.db.set_value.assert_called_once_with(state.STATE, 'STATE-1',
            {'last_read': 'RELAY-MSG-0000000009', 'last_seen': NOW}, update_modified=True)
        changed.assert_called_once_with('RELAY-CON-0000000001', 'reads')

    def test_a_new_row_has_a_hash_name_and_ignores_a_parallel_insert(self):
        site = fake_site()
        site.db.get_value.side_effect = [None, 'STATE-2']
        with patch.object(state, 'frappe', site), patch('relay_core.inbox.state_key', return_value='key'):
            self.assertEqual(state.ensure_state('RELAY-CON-0000000001'), 'STATE-2')
        args, kwargs = site.db.bulk_insert.call_args
        self.assertEqual(args[2][0][0], 'hash0')
        self.assertTrue(kwargs['ignore_duplicates'])
        self.assertTrue(site.db.get_value.call_args.kwargs['for_update'])

    def test_same_chat_position_is_not_written_again(self):
        view = {'name': 'RELAY-MSG-0000000001', 'offset': 4.0, 'atBottom': False}
        site = fake_site()
        site.db.get_value.side_effect = lambda doctype, name, field=None, **kw: (
            'STATE-1' if field == 'name' else json.dumps({'_active': 'WA', 'WA': view}))
        with patch.object(state, 'frappe', site), patch('relay_core.inbox.state_key', return_value='key'):
            state.save_chat_view('RELAY-CON-0000000001', 'WA', view)
            site.db.set_value.assert_not_called()
            state.save_chat_view('RELAY-CON-0000000001', 'WA', dict(view, offset=9.0))
        self.assertEqual(json.loads(site.db.set_value.call_args.args[3])['WA']['offset'], 9.0)


class InsertReadsTests(unittest.TestCase):
    def test_only_unknown_reads_are_inserted_with_hash_names(self):
        site = fake_site()
        site.get_all.side_effect = lambda doctype, filters, pluck: [filters['read_key'][1][0]]
        with patch.object(message_reads, 'frappe', site):
            self.assertTrue(message_reads.insert_reads([('C1', 'RELAY-MSG-0000000001'), ('C1', 'RELAY-MSG-0000000002')]))
        rows = site.db.bulk_insert.call_args.args[2]
        self.assertEqual([(row[0], row[7]) for row in rows], [('hash0', 'RELAY-MSG-0000000002')])
        self.assertTrue(site.db.bulk_insert.call_args.kwargs['ignore_duplicates'])

    def test_known_reads_write_nothing(self):
        site = fake_site()
        site.get_all.side_effect = lambda doctype, filters, pluck: filters['read_key'][1]
        with patch.object(message_reads, 'frappe', site):
            self.assertFalse(message_reads.insert_reads([('C1', 'RELAY-MSG-0000000001')]))
        site.db.bulk_insert.assert_not_called()


class MarkTests(unittest.TestCase):
    def mark(self, write_error=None):
        site = fake_site()
        site.parse_json.side_effect = json.loads
        site.get_doc.return_value = Mock(relay_contact='C1')
        fresh_write = Mock(side_effect=write_error)
        with patch.object(message_reads, 'frappe', site), patch.object(message_reads, 'require_access'), \
                patch.object(message_reads, 'readable_contact'), patch.object(state, 'fresh_write', fresh_write), \
                patch('relay_core.whatsapp_presence.mark_read') as self.receipts, \
                patch('relay_core.business_access.primary', return_value=('Customer', 'C9')):
            return message_reads.mark('C1', json.dumps(['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002']))

    def test_saved_reads_are_acknowledged_and_get_receipts(self):
        self.assertEqual(self.mark(), {'marked': ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002']})
        self.receipts.assert_called_once_with('C1', ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002'])

    def test_reads_lower_the_shared_unread_count_of_the_chat_each_message_belongs_to(self):
        def message(doctype, name):
            business = ('Supplier', 'S1') if name.endswith('2') else ('', '')
            values = {'relay_contact': 'C1', 'business_doctype': business[0], 'business_name': business[1]}
            return Mock(relay_contact='C1', get=values.get)
        site = fake_site()
        site.parse_json.side_effect = json.loads
        site.get_doc.side_effect = message
        with patch.object(message_reads, 'frappe', site), patch.object(message_reads, 'require_access'), \
                patch.object(message_reads, 'readable_contact'), patch('relay_core.whatsapp_presence.mark_read'), \
                patch.object(state, 'fresh_write', side_effect=lambda work: work()), \
                patch.object(message_reads, 'record_contact_reads') as record, \
                patch('relay_core.business_access.primary', return_value=('Customer', 'C9')):
            message_reads.mark('C1', json.dumps(['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002']))
        record.assert_called_once_with('C1', ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002'],
                                       {('Customer', 'C9'): 'RELAY-MSG-0000000001', ('Supplier', 'S1'): 'RELAY-MSG-0000000002'})

    def test_unsaved_reads_are_not_acknowledged_and_get_no_receipts(self):
        with self.assertRaises(state.StateWriteFailed):
            self.mark(state.StateWriteFailed('not saved'))
        self.receipts.assert_not_called()


class DeadlockClassTests(unittest.TestCase):
    def test_frappe_reports_snapshot_conflicts_as_deadlocks(self):
        from frappe.database.mariadb.database import MariaDBExceptionUtil
        self.assertTrue(MariaDBExceptionUtil.is_deadlocked(type('E', (Exception,), {})(1020, 'Record has changed')))
