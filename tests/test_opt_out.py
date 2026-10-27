"""Opt-out and opt-in keywords mark the number; a keyword gets no automatic reply."""
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import opt_out


def message(content, **values):
    return _dict({'name': 'MSG-1', 'channel': 'WA', 'sender_endpoint': '919876543210', 'direction': 'Incoming',
                  'content': content, **values})


class KeywordTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        self.fake = Mock()
        self.fake.db.get_single_value.side_effect = lambda doctype, field: self.settings.get(field)
        self.fake.db.get_value.return_value = 'CE-1'
        self.fake.utils.now_datetime.return_value = '2026-10-27 10:00:00'
        self.enterContext(patch.object(opt_out, 'frappe', self.fake))

    def test_only_an_exact_keyword_in_any_case_counts(self):
        for content, expected in (('STOP', True), (' stop\n', True), ('Unsubscribe', True), ('start', False),
                                  ('please stop', None), ('STOP!', None), ('', None), (None, None)):
            with self.subTest(content=content):
                self.assertIs(opt_out.choice(message(content)), expected)
        self.assertIsNone(opt_out.choice(message('STOP', direction='Outgoing')))
        self.assertTrue(opt_out.choice(message('STOP', legacy_source='LEG-1')))

    def test_keywords_come_from_settings(self):
        self.settings.update(opt_out_keywords='Quit\n  Opt out  \n', opt_in_keywords='Resume')
        self.assertTrue(opt_out.choice(message('opt OUT')))
        self.assertFalse(opt_out.choice(message('RESUME')))
        self.assertIsNone(opt_out.choice(message('STOP')))

    def test_stop_marks_the_number_and_start_clears_it(self):
        opt_out.on_message(message('Stop'))
        self.fake.db.set_value.assert_called_with('Relay Contact Endpoint', 'CE-1', {
            'marketing_opt_out': 1, 'opt_out_changed_at': '2026-10-27 10:00:00'})
        opt_out.on_message(message('START'))
        self.assertEqual(self.fake.db.set_value.call_args.args[2]['marketing_opt_out'], 0)
        self.fake.db.set_value.reset_mock()
        opt_out.on_message(message('Stop sending me offers'))
        self.fake.db.set_value.assert_not_called()


class HistoryTests(unittest.TestCase):
    """Imported keywords set the number's choice with their own time, once, without overriding a later change."""

    def setUp(self):
        self.fake = Mock()
        self.fake.db.get_single_value.return_value = None
        self.enterContext(patch.object(opt_out, 'frappe', self.fake))
        self.fake.get_all.return_value = [
            message('STOP', sent_at='2026-03-01 10:00:00', creation='2026-10-27 18:00:00'),
            message('START', sent_at='2026-03-05 10:00:00', creation='2026-10-27 18:00:00'),
            message('hello', sent_at='2026-03-09 10:00:00', creation='2026-10-27 18:00:00')]

    def test_the_newest_imported_keyword_sets_the_choice_at_its_own_time(self):
        self.fake.db.get_value.return_value = _dict(name='CE-1', opt_out_changed_at=None)
        opt_out.apply_history('WA', '919876543210')
        self.fake.db.set_value.assert_called_once_with('Relay Contact Endpoint', 'CE-1', {
            'marketing_opt_out': 0, 'opt_out_changed_at': '2026-03-05 10:00:00'})
        filters = self.fake.get_all.call_args.kwargs['filters']
        self.assertEqual((filters['channel'], filters['sender_endpoint'], filters['legacy_source']), ('WA', '919876543210', ['is', 'set']))

    def test_a_later_live_change_wins(self):
        self.fake.db.get_value.return_value = _dict(name='CE-1', opt_out_changed_at='2026-10-26 10:00:00')
        opt_out.apply_history('WA', '919876543210')
        self.fake.db.set_value.assert_not_called()

    def test_the_live_hook_leaves_imported_rows_to_the_history(self):
        opt_out.on_message(message('STOP', legacy_source='old-1'))
        self.fake.db.set_value.assert_not_called()
