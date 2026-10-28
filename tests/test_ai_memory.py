"""AI memory: event lines, address isolation, Day to Year rollups, idempotent re-runs and the loader order."""
import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict
from pypika import Table
from relay_core.ai import memory

TODAY = datetime.date(2026, 10, 28)
RECORD = ('Customer', 'C1')


def message(number, address, day, text, direction='Incoming', **values):
    at = datetime.datetime.combine(day, datetime.time(10, number % 60))
    row = _dict(name=f'RELAY-MSG-{number:010d}', relay_contact='R-' + address, channel='CH-1', direction=direction,
                sent_at=at, creation=at, content=text, message_data={'kind': 'text', 'text': text}, transcript=None,
                business_doctype=RECORD[0], business_name=RECORD[1], sender_endpoint=address, owner='staff@example.com',
                legacy_author=None, legacy_triage=0)
    return _dict(row, **values)


def sent(row):
    return (row.sent_at or row.creation).date()


def matches(value, condition):
    if isinstance(condition, list):
        operator, other = condition
        return value < other if operator == '<' else value >= other
    return value == condition


class FakeMemory(memory.Memory):
    """Memory rows and messages kept in lists shared by every address."""
    is_contact_key = False

    def __init__(self, store, inbox, address):
        super().__init__(*RECORD, address, today=TODAY)
        self.store, self.inbox = store, inbox

    def rows(self, level=None, **filters):
        filters = {**self.key, **({'level': level} if level else {}), **filters}
        found = [row for row in self.store if all(matches(row.get(key), value) for key, value in filters.items())]
        return [_dict(row) for row in sorted(found, key=lambda row: row['period_start'])]

    def save(self, row):
        if not row.get('name'):
            row.name = f'MEM-{len(self.store) + 1}'
            self.store.append(_dict(row, **self.key))
        else:
            next(item for item in self.store if item.name == row.name).update(row)

    def delete(self, row):
        self.store[:] = [item for item in self.store if item.name != row.name]

    def messages(self, since=None, until=None, after='', limit=memory.BATCH, newest_first=False):
        rows = sorted((row for row in self.inbox if row.sender_endpoint == self.address and row.name > after
                       and (not since or sent(row) >= since) and (not until or sent(row) < until)),
                      key=lambda row: row.name, reverse=newest_first)
        return rows[:limit]


def fake_model(model, prompt, timeout, reference):
    """Keep every previous and new line once with short fields, as a model that only merges would."""
    assert (timeout, reference) == (memory.MODEL_TIMEOUT, RECORD)
    value = json.loads(prompt)
    lines = [*value['previous_summary'].splitlines(), *(line for event in value['new_events'] for line in event.splitlines())]
    short = (' | '.join(field[:40] for field in line.split(' | ')) for line in lines)
    return {'lines': list(dict.fromkeys(short))}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.store, self.inbox = [], []
        self.model = self.enterContext(patch.object(memory, 'complete_json', side_effect=fake_model))
        self.enterContext(patch.object(memory, 'medium_of', return_value='WhatsApp'))
        self.name = self.enterContext(patch.object(memory, 'display_name', return_value=None))
        self.user = self.enterContext(patch.object(memory, 'user_name', side_effect=lambda user: user))
        self.enterContext(patch.object(memory, 'team_label', return_value='Essdee team'))

    def build(self, address):
        FakeMemory(self.store, self.inbox, address).build('Summary Model', datetime.date(2026, 1, 1))

    def summary(self, address, level, start):
        return next(row.summary for row in self.store if row.address == address and row.level == level
                    and row.period_start == start)

    def test_an_event_line_has_the_six_fields_and_no_inner_separator(self):
        row = message(1, '919800000001', TODAY, 'Need invoice | copy', message_data={'kind': 'document', 'attachment': 'FILE-9',
                      'media': {'filename': 'SINV-1.pdf'}, 'caption': 'Need invoice | copy'})
        line = memory.event_line(row, 'WhatsApp')
        self.assertEqual(line, '2026-10-28 10:01 | WhatsApp | 919800000001 | Need invoice copy | FILE-9 | -')
        self.assertTrue(memory.LINE.fullmatch(line))
        self.name.return_value = 'Atal Marketing'
        self.assertIn('| Atal Marketing |', memory.event_line(row, 'WhatsApp'), 'Incoming lines name the contact')
        reply = memory.event_line(message(2, '919800000001', TODAY, 'Sent', direction='Outgoing'), 'WhatsApp')
        self.assertIn('| staff@example.com |', reply)

    def test_two_addresses_of_one_record_never_share_a_summary(self):
        self.inbox += [message(1, 'A', TODAY, 'Order 10 boxes'), message(2, 'B', TODAY, 'Cancel my order'),
                       message(3, 'A', TODAY, 'Send the invoice')]
        self.build('A')
        self.build('B')
        first, second = self.summary('A', 'Day', TODAY), self.summary('B', 'Day', TODAY)
        self.assertIn('Order 10 boxes', first)
        self.assertIn('Send the invoice', first)
        self.assertNotIn('Cancel', first)
        self.assertEqual(second.count('\n'), 0)
        self.assertIn('Cancel my order', second)
        for call in self.model.call_args_list:
            events = json.loads(call.args[1])['new_events']
            self.assertEqual(len({line.split(' | ')[2] for line in events}), 1, 'One model call reads one address')

    def test_days_roll_into_weeks_months_and_a_year_and_covered_rows_are_pruned(self):
        days = [datetime.date(2026, 8, 10), datetime.date(2026, 9, 30), datetime.date(2026, 10, 20),
                datetime.date(2026, 10, 27), TODAY]
        self.inbox += [message(number, 'A', day, f'Request {number}') for number, day in enumerate(days, 1)]
        self.build('A')
        kept = sorted((row.level, row.period_start) for row in self.store)
        self.assertEqual(kept, [
            ('Day', datetime.date(2026, 10, 27)), ('Day', TODAY),
            ('Month', datetime.date(2026, 8, 1)), ('Month', datetime.date(2026, 9, 1)), ('Month', datetime.date(2026, 10, 1)),
            ('Week', datetime.date(2026, 10, 19)), ('Week', datetime.date(2026, 10, 26)),
            ('Year', datetime.date(2026, 1, 1))])
        year = self.summary('A', 'Year', datetime.date(2026, 1, 1))
        self.assertIn('Request 1', year)
        self.assertIn('Request 2', year)
        self.assertNotIn('Request 3', year, 'October is not finished')
        self.assertIn('Request 3', self.summary('A', 'Month', datetime.date(2026, 10, 1)))
        self.assertIn('Request 4', self.summary('A', 'Week', datetime.date(2026, 10, 26)))
        self.assertNotIn('Request 5', self.summary('A', 'Week', datetime.date(2026, 10, 26)), 'Today is not finished')
        week = next(row for row in self.store if row.level == 'Week' and row.period_start == datetime.date(2026, 10, 26))
        self.assertEqual(week.period_end, datetime.date(2026, 10, 31), 'A week stops at the month end')
        self.assertEqual(next(row for row in self.store if row.level == 'Year').message_count, 2)

    def test_a_second_run_without_new_messages_changes_nothing(self):
        self.inbox += [message(1, 'A', datetime.date(2026, 9, 30), 'Old'), message(2, 'A', TODAY, 'New')]
        self.build('A')
        before, calls = [dict(row) for row in self.store], self.model.call_count
        self.build('A')
        self.assertEqual([dict(row) for row in self.store], before)
        self.assertEqual(self.model.call_count, calls)
        self.inbox.append(message(3, 'A', TODAY, 'Newer'))
        self.build('A')
        self.assertEqual(self.model.call_count, calls + 1, 'Only the new message is folded')
        self.assertEqual(next(row for row in self.store if row.level == 'Day' and row.period_start == TODAY).message_count, 2)

    def test_backfill_folds_one_month_into_its_month_and_the_year_once(self):
        august = datetime.date(2026, 8, 1)
        self.inbox += [message(1, 'A', datetime.date(2026, 8, 10), 'August order'),
                       message(2, 'A', datetime.date(2026, 8, 20), 'August invoice'),
                       message(3, 'A', datetime.date(2026, 9, 2), 'September order')]
        FakeMemory(self.store, self.inbox, 'A').backfill('Summary Model', august)
        self.assertEqual(sorted((row.level, row.period_start, row.message_count) for row in self.store),
                         [('Month', august, 2), ('Year', datetime.date(2026, 1, 1), 2)])
        self.assertIn('August invoice', self.summary('A', 'Year', datetime.date(2026, 1, 1)))
        self.assertNotIn('September', self.summary('A', 'Month', august))
        calls = self.model.call_count
        FakeMemory(self.store, self.inbox, 'A').backfill('Summary Model', august)
        self.assertEqual(self.model.call_count, calls, 'A second backfill of the month folds nothing')

    def test_full_message_text_is_kept_up_to_the_message_limit_and_long_days_fold_in_parts(self):
        text = 'Need ' + 'blue shirts ' * 300
        self.inbox += [message(number, 'A', TODAY, text) for number in range(1, 13)]
        self.build('A')
        prompts = [json.loads(call.args[1]) for call in self.model.call_args_list]
        self.assertGreater(len(prompts), 1, 'Twelve long messages need more than one part')
        for prompt in prompts:
            self.assertLessEqual(sum(map(len, prompt['new_events'])), memory.EVENT_BUDGET)
        field = prompts[0]['new_events'][0].split(' | ')[3]
        self.assertEqual(len(field), memory.MAX_MESSAGE_LENGTH, 'Full text up to the limit, not a 200 character preview')
        self.assertEqual(self.store[0].message_count, 12)

    def test_input_over_the_prompt_limit_marks_the_row_failed_without_a_call(self):
        self.store.append(_dict(name='MEM-1', **{'business_doctype': RECORD[0], 'business_name': RECORD[1]}, address='A',
                                level='Day', period_start=TODAY, period_end=TODAY, channel='WhatsApp',
                                summary='x' * memory.MAX_JSON_PROMPT_LENGTH, last_message='', message_count=0))
        self.inbox.append(message(1, 'A', TODAY, 'Order'))
        with self.assertRaises(ValueError):
            self.build('A')
        self.model.assert_not_called()
        row = self.store[0]
        self.assertEqual((row.status, row.last_message), ('Failed', ''))
        self.assertIn('limit', row.error)

    def test_an_invalid_model_answer_is_rejected(self):
        for answer in ({'lines': ['hello']}, {'lines': 'x'}, {}):
            with self.subTest(answer=answer), patch.object(memory, 'complete_json', return_value=answer), \
                 self.assertRaises(ValueError):
                memory.summarize('Summary Model', '', ['2026-10-28 10:00 | WhatsApp | A | Hi | - | -'], RECORD)

    def test_an_overlong_line_is_cut_in_the_middle_of_its_text_and_keeps_the_file_id(self):
        long = '2026-10-28 10:00 | WhatsApp | Atal | Need ' + 'blue shirts ' * 40 + 'SINV-0042 | FILE-9 | sent'
        with patch.object(memory, 'complete_json', return_value={'lines': [long, '2026-10-28 11:00 | WhatsApp | A | Hi | - | -']}):
            lines = memory.summarize('Summary Model', '', ['event'], RECORD).splitlines()
        self.assertEqual(len(lines[0]), memory.MAX_LINE_LENGTH)
        self.assertTrue(memory.LINE.fullmatch(lines[0]))
        self.assertTrue(lines[0].startswith('2026-10-28 10:00 | WhatsApp | Atal | Need blue'))
        self.assertTrue(lines[0].endswith('SINV-0042 | FILE-9 | sent'))
        self.assertIn('…', lines[0])
        self.assertEqual(lines[1], '2026-10-28 11:00 | WhatsApp | A | Hi | - | -')

    def test_a_provider_error_marks_the_row_failed_and_keeps_its_summary_and_cursor(self):
        class DeadlineReached(TimeoutError):
            pass
        self.inbox.append(message(1, 'A', TODAY, 'Order 10 boxes'))
        self.build('A')
        before = dict(self.store[0])
        self.inbox.append(message(2, 'A', TODAY, 'Send the invoice'))
        self.model.side_effect = DeadlineReached('Deadline reached')
        with self.assertRaises(DeadlineReached):
            self.build('A')
        row = self.store[0]
        self.assertEqual((row.status, row.error), ('Failed', 'Deadline reached'))
        self.assertEqual((row.summary, row.last_message, row.message_count),
                         (before['summary'], before['last_message'], before['message_count']))
        self.model.side_effect = fake_model
        self.build('A')
        self.assertEqual((self.store[0].status, self.store[0].message_count), ('Ready', 2), 'The next run retries')

    def test_each_call_folds_a_bounded_chunk_of_messages(self):
        rows = [message(number, 'A', TODAY, f'Request {number}') for number in range(1, 131)]
        self.model.side_effect = None
        self.model.return_value = {'lines': ['2026-10-28 10:00 | WhatsApp | A | Requests 1 to 130 | - | -']}
        target = FakeMemory(self.store, self.inbox, 'A')
        target.fold_rows(target.row('Day', TODAY), (TODAY, TODAY), rows, 'Summary Model')
        sizes = [len(json.loads(call.args[1])['new_events']) for call in self.model.call_args_list]
        self.assertEqual(sizes, [60, 60, 10])

    def test_messages_are_placed_by_their_sent_time_not_their_creation(self):
        yesterday = datetime.date(2026, 10, 27)
        imported = message(1, 'A', yesterday, 'Imported order', creation=datetime.datetime(2026, 10, 28, 9))
        self.inbox += [imported, message(2, 'A', TODAY, 'Today', sent_at=None)]
        self.build('A')
        self.assertIn('Imported order', self.summary('A', 'Day', yesterday))
        self.assertIn('Today', self.summary('A', 'Day', TODAY))
        self.assertNotIn('Imported', self.summary('A', 'Day', TODAY))

    def test_system_senders_get_the_team_label_and_users_their_full_name(self):
        line = memory.event_line(message(1, 'A', TODAY, 'Sent', direction='Outgoing', owner='Administrator'), 'WhatsApp')
        self.assertIn('| Essdee team |', line)
        self.user.side_effect = {'old@example.com': 'Old Staff'}.get
        line = memory.event_line(message(2, 'A', TODAY, 'Sent', direction='Outgoing', owner='Administrator',
                                         legacy_author='old@example.com'), 'WhatsApp')
        self.assertIn('| Old Staff |', line)

    def test_secrets_are_redacted_before_the_model_reads_them(self):
        cases = {'My password: hunter2 please': 'My password: [redacted] please',
                 'Your OTP is 123456.': 'Your OTP is [redacted].', '4821 is your OTP': '[redacted] is your OTP',
                 'api_key=sk-abc123 token: xyz': 'api_key=[redacted] token: [redacted]',
                 'password Abc@123 reset': 'password [redacted] reset',
                 'Authorization Bearer abcdefgh12345': 'Authorization Bearer [redacted]',
                 'Forgot my password, ship 12 boxes to 641001': 'Forgot my password, ship 12 boxes to 641001'}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(memory.redact(text), expected)
        line = memory.event_line(message(1, 'A', TODAY, 'Login OTP 998877 for SO-1'), 'WhatsApp')
        self.assertIn('Login OTP [redacted] for SO-1', line)
        self.assertNotIn('998877', line)

    def test_the_loader_returns_levels_from_year_to_day_then_recent_messages(self):
        self.inbox += [message(1, 'A', datetime.date(2026, 9, 30), 'Old request'),
                       message(2, 'A', datetime.date(2026, 10, 27), 'Yesterday'), message(3, 'A', TODAY, 'Today one'),
                       message(4, 'A', TODAY, 'Today two'), message(5, 'B', TODAY, 'Other address')]
        self.build('A')
        text = FakeMemory(self.store, self.inbox, 'A').text(recent=2)
        headers = [block.splitlines()[0] for block in text.split('\n\n')]
        self.assertEqual(headers, ['Year 2026-01-01 to 2026-12-31', 'Month 2026-09-01 to 2026-09-30',
                                   'Week 2026-10-26 to 2026-10-31', 'Day 2026-10-27 to 2026-10-27',
                                   'Day 2026-10-28 to 2026-10-28', 'Recent messages'])
        recent = text.split('Recent messages\n')[1].splitlines()
        self.assertEqual([line.split(' | ')[3] for line in recent], ['Today one', 'Today two'])
        self.assertNotIn('Other address', text)


class SchedulingTests(unittest.TestCase):
    def test_without_a_memory_model_the_job_logs_once_and_does_nothing(self):
        fake = MagicMock()
        fake.db.get_single_value.return_value = None
        with patch.object(memory, 'frappe', fake), patch.object(memory, 'targets') as targets:
            memory.run()
        fake.logger.return_value.info.assert_called_once()
        targets.assert_not_called()
        fake.enqueue.assert_not_called()
        with patch.object(memory, 'frappe', fake), patch('relay_core.ai_features.is_enabled', return_value=True), \
             patch.object(memory, 'Memory') as built:
            memory.fold(*RECORD, 'A')
        built.assert_not_called()

    def test_only_addresses_with_newer_messages_are_queued_once(self):
        fake = MagicMock()
        fake.db.get_single_value.return_value = 'Summary Model'
        found = {(*RECORD, 'A'): 'RELAY-MSG-0000000009', (*RECORD, 'B'): 'RELAY-MSG-0000000004'}
        with patch.object(memory, 'frappe', fake), patch.object(memory, 'getdate', return_value=TODAY), \
             patch.object(memory, 'targets', return_value=found), \
             patch.object(memory, 'cursors', return_value={(*RECORD, 'B'): 'RELAY-MSG-0000000004'}):
            memory.run()
        fake.enqueue.assert_called_once()
        call = fake.enqueue.call_args
        self.assertEqual((call.kwargs['address'], call.kwargs['queue'], call.kwargs['deduplicate']), ('A', 'long', True))

    def test_addresses_without_an_incoming_message_get_no_memory(self):
        fake = MagicMock()
        fake.qb.DocType.return_value = Table('tabRelay Message')
        rows = [_dict(business_doctype='Customer', business_name='C1', relay_contact='R1', sender_endpoint='A',
                      direction='Outgoing', last='RELAY-MSG-0000000002'),
                _dict(business_doctype='Customer', business_name='C1', relay_contact='R1', sender_endpoint='A',
                      direction='Incoming', last='RELAY-MSG-0000000001'),
                _dict(business_doctype='Customer', business_name='C1', relay_contact='R2', sender_endpoint='B',
                      direction='Outgoing', last='RELAY-MSG-0000000003')]
        query = fake.qb.from_.return_value.select.return_value.where.return_value.where.return_value.groupby.return_value
        query.run.return_value = rows
        with patch.object(memory, 'frappe', fake), \
             patch.object(memory, 'timeline_time', return_value=Table('tabRelay Message').relay_timeline_time):
            self.assertEqual(memory.targets(TODAY), {('Customer', 'C1', 'A'): 'RELAY-MSG-0000000002'})
        where = fake.qb.from_.return_value.select.return_value.where.call_args.args[0]
        self.assertIn('relay_timeline_time', str(where), 'Targets select by sent time, not creation')

    def test_backfill_accepts_only_a_month_before_the_nightly_window(self):
        fake = MagicMock()
        fake.db.get_single_value.return_value = 'Summary Model'
        fake.throw.side_effect = ValueError
        with patch.object(memory, 'frappe', fake), patch.object(memory, 'window_start', return_value=datetime.date(2026, 10, 1)):
            for month in ('2026-10', 'August'):
                with self.subTest(month=month), self.assertRaises(ValueError):
                    memory.backfill(month)
            with patch.object(memory, 'targets', return_value={(*RECORD, 'A'): 'RELAY-MSG-0000000008'}) as targets:
                self.assertEqual(memory.backfill('2026-08'), 1)
        targets.assert_called_once_with(datetime.date(2026, 8, 1), datetime.date(2026, 9, 1))
        fake.only_for.assert_called_with('System Manager')
        self.assertEqual(fake.enqueue.call_args.kwargs['month'], '2026-08')

    def test_backfill_can_be_limited_to_one_record_or_address(self):
        fake = MagicMock()
        fake.db.get_single_value.return_value = 'Summary Model'
        found = {(*RECORD, 'A'): 'M-1', (*RECORD, 'B'): 'M-2', ('Customer', 'C2', 'A'): 'M-3'}
        with patch.object(memory, 'frappe', fake), patch.object(memory, 'targets', return_value=found), \
             patch.object(memory, 'window_start', return_value=datetime.date(2026, 10, 1)):
            self.assertEqual(memory.backfill('2026-08', *RECORD), 2)
            self.assertEqual(memory.backfill('2026-08', *RECORD, address='B'), 1)
            self.assertEqual(fake.enqueue.call_args.kwargs['address'], 'B')
            self.assertEqual(memory.backfill('2026-08', address='A'), 2)
            self.assertEqual(memory.backfill('2026-08'), 3)

    def test_weeks_start_on_monday_and_stop_at_the_month_end(self):
        self.assertEqual(memory.period('Week', datetime.date(2026, 10, 1)), (datetime.date(2026, 10, 1), datetime.date(2026, 10, 4)))
        self.assertEqual(memory.period('Week', datetime.date(2026, 10, 14)), (datetime.date(2026, 10, 12), datetime.date(2026, 10, 18)))
        self.assertEqual(memory.period('Month', TODAY), (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)))
        self.assertEqual(memory.period('Year', TODAY), (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)))
