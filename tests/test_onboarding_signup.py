"""WhatsApp signup sessions, business details, Get started rights and the relay_signup callback."""
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from channel_fakes import FakeSite
from relay_core.automation import projection
from relay_core.hub import HubError
from relay_core.onboarding import api, details, progress, signup, test_message
from relay_core.onboarding.messages import OnboardingError, text

SESSION = 'sus_' + 'a' * 32
DRAFT = {'name': 'Acme', 'email': 'admin@acme.example', 'website': '', 'country': 'IN', 'timezone': 'UTC+05:30',
         'display_name': 'Acme', 'category': 'OTHER', 'description': ''}


def session(state='working', **values):
    steps = [{'name': name, 'status': 'done' if state == 'completed' else 'pending', 'at': None}
             for name in ('exchange', 'verify', 'channel', 'subscribe', 'register')]
    return dict({'session_id': SESSION, 'flow': 'new', 'flow_actual': 'new', 'state': state, 'steps': steps,
                 'error': None, 'channel_key': 'wa-120', 'waba_id': '230', 'business_id': '330',
                 'phone': {'id': '120', 'display_phone_number': '+91 90000 00120', 'verified_name': 'Acme'},
                 'payment_method_ready': False, 'coexistence': None, 'expires_at': '', 'updated_at': ''}, **values)


class SignupSite(FakeSite):
    def __init__(self, **tables):
        super().__init__(**tables)
        self.frappe.cache = SimpleNamespace(lock=Mock(return_value=nullcontext()),
                                            make_key=lambda key: key)
        self.frappe.utils = SimpleNamespace(now_datetime=lambda: 'now')
        self.frappe.publish_realtime = Mock()
        self.frappe.realtime = SimpleNamespace(get_doctype_room=lambda doctype: 'doctype:' + doctype)
        self.frappe.db.get_single_value = lambda doctype, field: {'hub_origin': 'https://hub.example.com'}.get(field)
        users = {}

        def get_doc(doctype, name=None):
            if doctype == 'User':
                return users.setdefault(name, SimpleNamespace(roles=[], append=lambda field, row: users[name].roles.append(
                    SimpleNamespace(**row)), save=Mock()))
            return FakeSite.get_doc(self, doctype, name)
        self.users = users
        self.frappe.get_doc = get_doc
        self.frappe.db.exists = lambda doctype, filters=None: doctype == 'User' or bool(
            self.rows(doctype, {'name': filters} if isinstance(filters, str) else filters))


class SignupTests(unittest.TestCase):
    def setUp(self):
        self.site = SignupSite(Relay_Channel=[{'channel': 'WhatsApp', 'hub_channel': 'wa-120', 'name': 'Acme-001'}])
        self.hub = Mock()
        self.sync = Mock()
        for item in (patch.object(signup, 'frappe', self.site.frappe), patch.object(signup, 'hub', return_value=self.hub),
                     patch('relay_core.channel_sync.sync', self.sync)):
            item.start()
            self.addCleanup(item.stop)

    def test_start_stores_the_session_and_returns_the_hub_window(self):
        launch = 'https://hub.example.com/onboard/whatsapp/' + SESSION + '#secret'
        self.hub.call_tool.return_value = {'session': session('created'), 'launch_url': launch}
        self.site.frappe.session.user = 'admin@acme.example'
        result = signup.start('coexistence', DRAFT)
        tool, arguments = self.hub.call_tool.call_args.args
        self.assertEqual((tool, arguments['flow'], arguments['actor']), ('whatsapp.signup.start', 'coexistence', 'admin@acme.example'))
        self.assertEqual(arguments['prefill']['business'], {'name': 'Acme', 'email': 'admin@acme.example', 'country': 'IN',
                                                            'timezone': 'UTC+05:30'})
        self.assertEqual(result['launch_url'], launch)
        row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual((row.session_id, row.status, row.started_by), (SESSION, 'Started', 'admin@acme.example'))

    def test_a_window_on_another_origin_is_refused(self):
        for url in ('https://evil.example.com/onboard/whatsapp/' + SESSION, 'https://hub.example.com/onboard/whatsapp/sus_' + 'b' * 32,
                    'https://hub.example.com/onboard/whatsapp/' + SESSION + '?x=1'):
            self.hub.call_tool.return_value = {'session': session('created'), 'launch_url': url}
            with self.subTest(url=url), self.assertRaises(OnboardingError) as caught:
                signup.start('new', DRAFT)
            self.assertEqual(caught.exception.code, 'launch_url_invalid')

    def test_completion_runs_once_and_makes_the_starter_a_manager(self):
        self.hub.call_tool.return_value = session('working')
        signup.store(session('working'), actor='admin@acme.example')
        self.sync.assert_not_called()
        signup.status(SESSION)
        self.hub.call_tool.return_value = session('completed', payment_method_ready=True)
        result = signup.status(SESSION)
        signup.status(SESSION)
        self.sync.assert_called_once_with()
        self.assertEqual(result['channel'], 'Acme-001')
        row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual((row.status, row.channel, row.payment_method_ready, row.hub_channel), ('Completed', 'Acme-001', 1, 'wa-120'))
        self.assertEqual([role.role for role in self.site.users['admin@acme.example'].roles], ['Relay Communication Manager'])
        self.assertEqual(len(self.site.queued), 1)
        self.site.frappe.publish_realtime.assert_called_with('relay_changed', {'kind': 'onboarding', 'session': SESSION},
                                                             room='doctype:Relay WhatsApp Signup', after_commit=True)

    def test_errors_read_in_relay_words(self):
        cases = ((session('cancelled', error={'meta_step': 'PHONE_NUMBER_VERIFICATION'}), 'cancelled', 'phone number verification'),
                 (session('failed', error={'code': 'register_rate_limited', 'retryable': False}), 'register_rate_limited', '72 hours'),
                 (session('failed', error={'code': 'meta_odd', 'message': 'Meta said token=abc no', 'retryable': True}), 'meta_odd', 'Meta said [hidden] no'))
        for value, code, words in cases:
            with self.subTest(code=code):
                error = signup.shown(signup.checked_session(value))['error']
                self.assertEqual(error['code'], code)
                self.assertIn(words, error['message'])

    def test_hub_error_codes_become_onboarding_errors(self):
        for detail, code in (('Signup is off · code signup_unavailable', 'signup_unavailable'),
                             ('code not_found', 'session_not_found'), ('', 'hub_unavailable')):
            self.hub.call_tool.side_effect = HubError('rejected', detail=detail)
            with self.subTest(code=code), self.assertRaises(OnboardingError) as caught:
                signup.status(SESSION)
            self.assertEqual(caught.exception.code, code)

    def test_malformed_sessions_and_ids_are_refused(self):
        with self.assertRaises(ValueError):
            signup.status('sus_bad')
        for value in ({'session_id': SESSION, 'state': 'odd'}, {'session_id': '../x', 'state': 'working'}, []):
            with self.subTest(value=value), self.assertRaises((OnboardingError, ValueError)):
                signup.store(value)

    def test_core_imported_history_never_goes_back(self):
        signup.store(session('working'))
        self.site.set_value('Relay WhatsApp Signup', SESSION, {'history_status': 'Done', 'history_progress': 100})
        signup.store(session('completed', coexistence={'contacts': 'requested', 'history': 'requested', 'history_progress': 30}))
        row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual((row.history_status, row.history_progress, row.contacts_status), ('Done', 100, 'Requested'))


class SignupEventTests(unittest.TestCase):
    def project(self, payload, result):
        event = Mock(payload=json.dumps(payload), projection_status='Pending')
        fake = Mock()
        fake.get_doc.return_value = event
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'set_status') as status, \
                patch.object(signup, 'status', side_effect=result) as read:
            projection.project('RELAY-EVT-1')
        return status, read

    def test_a_relay_signup_event_reads_the_session(self):
        status, read = self.project({'object': 'relay_signup', 'session_id': SESSION, 'state': 'working'}, [{}])
        read.assert_called_once_with(SESSION)
        status.assert_called_once_with('RELAY-EVT-1', 'Projected')

    def test_a_failed_read_or_bad_id_marks_the_event_failed(self):
        for payload, result in (({'object': 'relay_signup', 'session_id': SESSION}, OnboardingError('hub_unavailable')),
                                ({'object': 'relay_signup', 'session_id': 'x'}, [{}])):
            with self.subTest(payload=payload), patch.object(signup, 'frappe', SimpleNamespace(
                    throw=lambda message, exception=ValueError: (_ for _ in ()).throw(exception(message)),
                    ValidationError=ValueError)):
                status, _ = self.project(payload, result)
            status.assert_called_once_with('RELAY-EVT-1', 'Failed')


class DetailsTests(unittest.TestCase):
    def check(self, **values):
        fake = SimpleNamespace(parse_json=json.loads, throw=lambda message: (_ for _ in ()).throw(ValueError(message)),
                               db=SimpleNamespace(exists=lambda doctype, filters: filters == {'code': 'in'}))
        with patch.object(details, 'frappe', fake):
            return details.checked({**DRAFT, 'no_website': True, **values})

    def test_valid_details_are_cleaned(self):
        draft = self.check(name='  Acme   Traders ', country='in', display_name='', website='https://acme.example')
        self.assertEqual((draft['name'], draft['country'], draft['display_name']), ('Acme Traders', 'IN', 'Acme Traders'))

    def test_wrong_details_name_the_field(self):
        for values, words in (({'name': ''}, 'business name'), ({'email': 'nope'}, 'email'), ({'website': 'acme', 'no_website': False}, 'website'),
                              ({'country': 'XX'}, 'country'), ({'timezone': 'Asia/Kolkata'}, 'time zone'),
                              ({'category': 'SPAM'}, 'category'), ({'name': 'x' * 101}, 'at most 100')):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, words):
                self.check(**values)

    def test_no_website_clears_the_website(self):
        self.assertEqual(self.check(website='junk')['website'], '')

    def test_time_zone_offsets_and_prefill(self):
        self.assertEqual(details.utc_offset('Asia/Kolkata'), 'UTC+05:30')
        self.assertEqual(details.utc_offset('America/St_Johns')[:7], 'UTC-03:')
        self.assertEqual(details.utc_offset('Nowhere/City'), 'UTC+00:00')
        self.assertNotIn('website', details.prefill(DRAFT)['business'])
        self.assertEqual(details.prefill(dict(DRAFT, website='https://a.example'))['business']['website'], 'https://a.example')


class StepTests(unittest.TestCase):
    def step(self, connected=True, draft=True, channels=(), completed=False, others=()):
        with patch.object(progress, 'is_completed', return_value=completed), \
                patch.object(progress, 'is_connected', return_value=connected), \
                patch.object(progress, 'other_channels', return_value=list(others)), \
                patch.object(details, 'saved', return_value=DRAFT if draft else None):
            return progress.current_step([SimpleNamespace(enabled=enabled) for enabled in channels])

    def test_the_first_open_step_is_shown(self):
        self.assertEqual(self.step(connected=False), 'hub')
        self.assertEqual(self.step(draft=False), 'business')
        self.assertEqual(self.step(), 'number')
        self.assertEqual(self.step(channels=(0,)), 'number')
        self.assertEqual(self.step(channels=(1,)), 'ready')
        self.assertEqual(self.step(completed=True, connected=False), 'done')

    def test_a_telegram_or_email_channel_alone_makes_the_site_ready(self):
        mailbox = SimpleNamespace(name='mail', channel='Email')
        self.assertEqual(self.step(draft=False, others=[mailbox]), 'ready')
        self.assertEqual(self.step(connected=False, others=[mailbox]), 'hub')


class RightsTests(unittest.TestCase):
    def call(self, method, roles, *args, user='user@acme.example', **kwargs):
        fake = SimpleNamespace(session=SimpleNamespace(user=user), get_roles=Mock(return_value=list(roles)),
                               throw=lambda message, exception=ValueError: (_ for _ in ()).throw(exception(message)),
                               PermissionError=PermissionError, db=SimpleNamespace(set_single_value=Mock()))
        with patch.object(api, 'frappe', fake), patch.object(api, 'require_access'), \
                patch.object(api, 'can_configure', return_value='System Manager' in roles), \
                patch.object(api, 'can_manage', return_value=bool(set(roles) & {'System Manager', 'Relay Communication Manager'})), \
                patch.object(progress, 'state', return_value={'step': 'hub'}), \
                patch.object(api.enrolment, 'connect', return_value={'connected': True}), \
                patch.object(api.signup, 'start', return_value={'session': {}}), \
                patch.object(details, 'saved', return_value=DRAFT):
            return getattr(api, method)(*args, **kwargs), fake

    def test_only_a_system_manager_sets_up_relay(self):
        for method, args in (('connect_hub', ()), ('start_whatsapp', ('new',)), ('resume_signup', (SESSION,)),
                             ('cancel_signup', (SESSION,)), ('send_test', ('Acme-001', '+919000000001')), ('finish', ())):
            for roles in (('Relay Communication User',), ('Relay Communication Manager',)):
                with self.subTest(method=method, roles=roles), self.assertRaises(PermissionError):
                    self.call(method, roles, *args)
        self.assertEqual(self.call('connect_hub', ('System Manager',))[0], {'connected': True})
        result, fake = self.call('finish', ('System Manager',))
        self.assertEqual(result, {'completed': True})
        fake.db.set_single_value.assert_called_once_with('Relay Settings', 'onboarding_completed', 1)

    def test_managers_read_the_state_and_users_do_not(self):
        self.assertEqual(self.call('state', ('Relay Communication Manager',))[0], {'step': 'hub'})
        with self.assertRaises(PermissionError):
            self.call('state', ('Relay Communication User',))

    def test_a_known_failure_reaches_the_browser_as_text(self):
        fake = SimpleNamespace(session=SimpleNamespace(user='Administrator'), get_roles=Mock(return_value=[]),
                               throw=lambda message, exception=ValueError: (_ for _ in ()).throw(exception(message)),
                               PermissionError=PermissionError)
        with patch.object(api, 'frappe', fake), patch.object(api, 'require_access'), \
                patch.object(details, 'saved', return_value=None), \
                self.assertRaisesRegex(api.OnboardingFailed, 'business details'):
            api.start_whatsapp('new')

    def test_connect_returns_the_error_code_and_text(self):
        with patch.object(api.enrolment, 'connect', side_effect=OnboardingError('token_revoked')), \
                patch.object(progress, 'is_connected', return_value=False), \
                patch.object(api, 'frappe', SimpleNamespace(session=SimpleNamespace(user='Administrator'))), \
                patch.object(api, 'require_access'):
            result = api.connect_hub()
        self.assertEqual(result, {'connected': False, 'error': {'code': 'token_revoked', 'message': text('token_revoked')}})


class PatchTests(unittest.TestCase):
    def run_patch(self, channels):
        from relay_core.patches.v1_0 import mark_existing_onboarded
        site = FakeSite(Relay_Channel=channels)
        site.frappe.db.set_single_value = Mock()
        with patch.object(mark_existing_onboarded, 'frappe', site.frappe):
            mark_existing_onboarded.execute()
        return site.frappe.db.set_single_value

    def test_a_site_with_any_enabled_channel_skips_get_started(self):
        for channels in ([{'channel': 'WhatsApp', 'enabled': 1}], [{'channel': 'WhatsApp', 'enabled': 0}, {'channel': 'Telegram', 'enabled': 1}],
                         [{'channel': 'Email', 'enabled': 1}]):
            with self.subTest(channels=channels):
                self.run_patch(channels).assert_called_once_with(
                    'Relay Settings', {'onboarding_completed': 1, 'enrolment_source': 'Manual'})

    def test_a_new_or_disabled_site_keeps_get_started(self):
        self.run_patch([]).assert_not_called()
        self.run_patch([{'channel': 'WhatsApp', 'enabled': 0}, {'channel': 'Email', 'enabled': 0}]).assert_not_called()


class BusinessNameTests(unittest.TestCase):
    def name(self, company, app_name):
        fake = SimpleNamespace(db=SimpleNamespace(get_single_value=Mock(return_value=app_name)), local=SimpleNamespace(site='acme.example.com'))
        with patch.object(details, 'frappe', fake):
            return details.business_name({'company_name': company} if company else {})

    def test_frappe_default_app_name_is_not_a_business_name(self):
        self.assertEqual(self.name('Acme Pvt Ltd', 'Frappe'), 'Acme Pvt Ltd')
        self.assertEqual(self.name(None, 'Acme ERP'), 'Acme ERP')
        self.assertEqual(self.name(None, 'Frappe'), 'acme.example.com')


class TestMessageTests(unittest.TestCase):
    """A new site has no business records, so the test message starts an unlinked chat."""
    def setUp(self):
        self.endpoints = {'RELAY-CON-1': 'RCE-1'}
        self.fake = SimpleNamespace(throw=Mock(side_effect=ValueError), db=SimpleNamespace(
            exists=Mock(return_value=True),
            get_value=Mock(side_effect=lambda doctype, filters, field: self.endpoints.get(filters['relay_contact']))))
        self.start = Mock(return_value={'action': 'A-1', 'status': 'Submitted', 'message': 'MSG-1'})
        for item in (patch.object(test_message, 'frappe', self.fake), patch.object(test_message, 'connection_value', return_value='acme'),
                     patch('relay_core.messaging_api.destination_number', return_value='919876500001'),
                     patch('relay_core.onboarding.coexistence.contact_for', return_value='RELAY-CON-1'),
                     patch('relay_core.contact_lifecycle.endpoint_key', return_value='key'),
                     patch('relay_core.conversation_start.send', self.start)):
            item.start()
            self.addCleanup(item.stop)

    def test_sends_hello_world_without_a_business_record_and_a_double_click_is_one_message(self):
        self.assertEqual(test_message.send('Acme-1', '+91 98765 00001')['message'], 'MSG-1')
        test_message.send('Acme-1', '+91 98765 00001')
        first, second = self.start.call_args_list
        self.assertEqual(first.args[:4], ('RELAY-CON-1', 'RCE-1', 'template', {'name': 'hello_world', 'language': 'en_US', 'components': []}))
        self.assertEqual(first.args[4], second.args[4])
        self.assertEqual(len(first.args), 5)

    def test_another_sites_or_a_disabled_channel_is_refused(self):
        self.fake.db.exists.return_value = False
        with self.assertRaises(ValueError):
            test_message.send('Other-1', '+91 98765 00001')
        self.start.assert_not_called()

    def test_a_number_on_two_contacts_is_refused(self):
        self.endpoints.clear()
        with self.assertRaises(ValueError):
            test_message.send('Acme-1', '+91 98765 00001')
        self.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
