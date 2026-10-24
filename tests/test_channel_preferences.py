import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


class ChannelPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.service = module('relay_core/channel_preferences.py', self.f)
        self.options = Mock(return_value=[dict(value='TG', endpoint='E1', provider='Telegram'),
                                          dict(value='EM', endpoint='E2', provider='Email')])
        self.binding = Mock()
        self.patch = patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(
            business_channels=self.options, ensure_business_binding=self.binding)})
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.f.get_all.return_value = [Doc(name='P1', endpoint='E1', priority=1), Doc(name='P2', endpoint='E2', priority=2)]

    def resolve(self, **kwargs):
        return self.service.resolve('PERSON', 'Customer', 'C1', **kwargs)

    def test_scope_includes_person_business_type_and_name(self):
        self.assertEqual(self.resolve()['endpoint'], 'E1')
        filters = self.f.get_all.call_args.kwargs['filters']
        self.assertEqual(filters['consent'], 'Granted')
        key = filters['scope_key']
        for args in [('OTHER', 'Customer', 'C1'), ('PERSON', 'Supplier', 'C1'), ('PERSON', 'Customer', 'C2')]:
            self.assertNotEqual(self.service.scope_key(*args), key)
        self.options.assert_called_with('PERSON', 'Customer', 'C1')

    def test_unavailable_or_unconfigured_channel_falls_back_before_admission(self):
        self.options.return_value.pop(0)
        self.assertEqual(self.resolve()['channel'], 'EM')
        self.assertEqual(self.resolve(previous_status='Rejected')['channel'], 'EM')
        with self.assertRaises(ValueError): self.resolve(providers=['Telegram'])
        with self.assertRaises(ValueError): self.resolve(channels=['TG'])

    def test_uncertain_pending_and_accepted_never_resolve_another_channel(self):
        for state in ('Uncertain', 'Dispatching', 'Queued', 'Submitted'):
            with self.subTest(state=state), self.assertRaises(ValueError): self.resolve(previous_status=state)
        self.options.assert_not_called(); self.f.get_all.assert_not_called()

    def test_missing_consent_and_equal_priorities_do_not_guess(self):
        self.f.get_all.return_value[1].priority = 1
        with self.assertRaisesRegex(ValueError, 'priorities'): self.resolve()
        self.f.get_all.return_value = []
        with self.assertRaisesRegex(ValueError, 'consented'): self.resolve()

    def test_recovery_checks_original_consent_and_binding_without_reselection(self):
        selection = self.resolve()
        row = Doc(scope_key=self.service.scope_key('PERSON','Customer','C1'), endpoint='E1', consent='Granted')
        self.f.get_doc.side_effect = lambda dt,name: row if dt == 'Relay Channel Preference' else Doc(channel='Telegram',account=selection['account'])
        self.service.recheck('PERSON','Customer','C1',selection)
        self.f.get_all.reset_mock()
        row.consent = 'Denied'
        with self.assertRaisesRegex(ValueError, 'consent'): self.service.recheck('PERSON','Customer','C1',selection)
        row.consent = 'Granted'; row.scope_key = self.service.scope_key('PERSON','Supplier','C1')
        with self.assertRaises(ValueError): self.service.recheck('PERSON','Customer','C1',selection)
        self.f.get_all.assert_not_called()
