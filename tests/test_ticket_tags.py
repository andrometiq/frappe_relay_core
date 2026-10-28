"""Ticket tags and notifications service boundary tests; no site data is created."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class TicketTagTests(unittest.TestCase):
    def setUp(self):
        def throw(message, exception=ValueError): raise exception(message)
        self.logs = Mock()
        self.f = types.SimpleNamespace(throw=throw, whitelist=lambda **kw: lambda fn: fn, PermissionError=PermissionError,
            parse_json=__import__('json').loads, session=types.SimpleNamespace(user='author@example.invalid'),
            db=types.SimpleNamespace(get_value=Mock(return_value=1)), has_permission=Mock(return_value=True),
            publish_realtime=Mock(), utils=types.SimpleNamespace(get_fullname=lambda user: user.split('@')[0].title()))
        self.tickets = types.ModuleType('relay_core.tickets')
        self.tickets.permission = Mock(return_value=True)
        self.tickets._episode_transition = types.SimpleNamespace(get=lambda: None)
        log_module = types.ModuleType('notification_log')
        log_module.make_notification_logs = self.logs
        modules = {'frappe': self.f, 'relay_core.tickets': self.tickets,
                   'relay_core.permissions': types.SimpleNamespace(require_access=Mock()),
                   'relay_core.api': types.SimpleNamespace(validate_reference=Mock()),
                   'frappe.desk.doctype.notification_log.notification_log': log_module}
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('tested_ticket_tags', Path('relay_core/ticket_tags.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def ticket(self, tagged=(), assigned_to=None, previous=None):
        doc = types.SimpleNamespace(name='TKT-00001', subject='Refund <late>', priority='High',
            assigned_to=assigned_to, watchers=[types.SimpleNamespace(user=user) for user in tagged],
            flags=types.SimpleNamespace(relay_quiet_tags=False), get_doc_before_save=lambda: previous)
        doc.get = lambda key, default=None: getattr(doc, key, default)
        return doc

    def test_user_list_rejects_duplicates_wrong_types_and_too_many(self):
        self.assertEqual(self.module.user_list('["a@example.invalid"]'), ['a@example.invalid'])
        self.assertEqual(self.module.user_list(None), [])
        for values in (['a', 'a'], [1], [''], ['u%s' % i for i in range(21)], {'user': 'a'}):
            with self.assertRaises(ValueError): self.module.user_list(values)

    def test_validate_denies_new_tag_without_conversation_access(self):
        self.module.validate(self.ticket(['agent@example.invalid']))
        self.tickets.permission.return_value = False
        with self.assertRaises(PermissionError): self.module.validate(self.ticket(['agent@example.invalid']))
        # A user tagged before access changed does not block unrelated saves.
        previous = self.ticket(['agent@example.invalid'])
        self.module.validate(self.ticket(['agent@example.invalid'], previous=previous))
        with self.assertRaises(ValueError): self.module.validate(types.SimpleNamespace(get=lambda key: 'Critical'))

    def test_new_assignee_and_new_tags_are_notified_once(self):
        previous = self.ticket(['old@example.invalid'], assigned_to='old@example.invalid')
        doc = self.ticket(['old@example.invalid', 'new@example.invalid', 'owner@example.invalid'],
                          assigned_to='owner@example.invalid', previous=previous)
        self.module.on_update(doc)
        (assigned, users), (tagged, tag_users) = [entry.args for entry in self.logs.call_args_list]
        self.assertEqual((assigned['type'], users), ('Assignment', ['owner@example.invalid']))
        self.assertEqual((tagged['type'], tag_users), ('Mention', ['new@example.invalid']))
        self.assertEqual(assigned['link'], '/relay#/tickets?ticket=TKT-00001')
        self.assertIn('Refund &lt;late&gt;', assigned['subject'])
        notice = self.f.publish_realtime.call_args_list[0]
        self.assertEqual(notice.args[0], 'relay_ticket_notice')
        self.assertEqual(notice.kwargs['user'], 'owner@example.invalid')
        self.assertEqual(notice.args[1]['subject'], 'Refund <late>')

    def test_notifications_skip_actor_and_users_without_access(self):
        self.tickets.permission.side_effect = lambda doc, user: user != 'blocked@example.invalid'
        sent = self.module.notify(self.ticket(), ['author@example.invalid', 'blocked@example.invalid', 'ok@example.invalid'],
                                  'Mention', 'Author tagged you on a ticket')
        self.assertEqual(sent, ['ok@example.invalid'])
        self.logs.reset_mock()
        self.assertEqual(self.module.notify(self.ticket(), ['author@example.invalid'], 'Mention', 'x'), [])
        self.logs.assert_not_called()

    def test_internal_episode_saves_stay_silent(self):
        doc = self.ticket(['new@example.invalid'], assigned_to='owner@example.invalid')
        self.tickets._episode_transition = types.SimpleNamespace(get=lambda: doc)
        self.module.on_update(doc)
        self.logs.assert_not_called()

    def test_comment_rejects_empty_body_and_inaccessible_mention_before_writing(self):
        self.f.get_doc = Mock()
        with self.assertRaises(ValueError): self.module.add_comment('TKT-00001', '  ')
        ticket = self.ticket()
        ticket.check_permission = Mock()
        self.f.get_doc.return_value = ticket
        self.tickets.permission.return_value = False
        with self.assertRaises(PermissionError):
            self.module.add_comment('TKT-00001', 'Please check', ['blocked@example.invalid'])
        self.assertEqual(self.f.get_doc.call_count, 1)


if __name__ == '__main__':
    unittest.main()
