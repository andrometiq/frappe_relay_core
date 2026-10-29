"""Deterministic privacy boundaries, including actual adapter and delivery wiring."""
import json
import unittest
from unittest.mock import patch

import test_ai_skills as fixtures
from relay_core.ai import adapter, reply_guard, service


class ReplyGuardTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.ai.knowledge.prompt', return_value=''))
        self.f = fixtures.framework()
        self.f.db.exists.return_value = True
        self.f.get_doc.return_value = fixtures.Doc(email='public@example.test', phone_no='+91 444 555 6666')
        self.f.get_all.side_effect = lambda dt, filters, **kw: [name for name in filters['name'][1]
            if name in {'Customer': ['Acme Traders', 'Other Retailer', 'Local Company', 'Branch Company'],
                        'Supplier': ['Private Supplier', 'Branch Company'], 'Company': ['Branch Company']}[dt]]
        self.enterContext(patch.object(reply_guard, 'frappe', self.f))
        self.enterContext(patch('relay_core.business_access.candidates', return_value=[('Customer', 'Acme Traders')]))
        self.skill = fixtures.Doc(instructions='These are twelve private words that must never be copied into customer replies.')
        self.scope = dict(endpoint='+91 999 888 7777', company='Local Company', contact='SELF',
                          business=['Customer', 'Acme Traders'])

    def check(self, text, **kw):
        return reply_guard.check(text, self.skill, self.scope, **kw)

    def test_own_and_public_endpoints_and_business_names_pass(self):
        for text in ('Hello Acme Traders, your balance is 1250.50.', 'Call +91 (999) 888-7777.',
                     'Call +91 444 555 6666 or PUBLIC@example.test.', 'Your order on 2026-10-29 is ready.'):
            with self.subTest(text=text):
                self.check(text)
        self.scope['endpoint'] = 'sender@example.test'
        self.check('We can email SENDER@example.test.')

    def test_foreign_email_and_phone_fail_without_exposing_hit(self):
        for text in ('Email another@example.test', 'Call +1 (555) 123-4567', 'Phone: 9876543210'):
            with self.subTest(text=text), self.assertRaisesRegex(reply_guard.ReplyBlocked, '^' + reply_guard.REASON + '$'):
                self.check(text)

    def test_other_customer_and_supplier_names_use_only_indexed_exact_queries(self):
        for text in ('Contact Other Retailer today.', 'Private Supplier has a balance of 5000.'):
            with self.subTest(text=text), self.assertRaises(reply_guard.ReplyBlocked):
                self.check(text)
        for call in self.f.get_all.call_args_list:
            self.assertEqual(set(call.kwargs['filters']), {'name'})
            self.assertEqual(call.kwargs['filters']['name'][0], 'in')
        self.f.db.sql.assert_not_called()

    def test_instruction_system_and_reply_style_chunks_block_at_twelve_words(self):
        self.skill.reply_style = 'Always answer with these twelve private style words that belong only to our team.'
        for source in (self.skill.instructions, adapter.SYSTEM_RULES, self.skill.reply_style):
            words = source.split()
            with self.subTest(source=source), self.assertRaises(reply_guard.ReplyBlocked):
                self.check(' '.join(words[:12]).upper())
            self.check(' '.join(words[:11]))

    def test_dates_are_not_phones(self):
        for date in ('2026-10-29', '29-10-2026', '29/10/2026', '29.10.2026'):
            with self.subTest(date=date):
                self.check(f'Your order on {date} is ready.')
                self.check(f'Your order on {date} 1250 is ready.')

    def test_document_numbers_are_not_phones(self):
        for name in ('SINV-2026-00012', 'ACC-PAY-2026-00045', 'SINV-2026-000012',
                     'ACC-PAY-2026-000045', 'INV/2026/1234567890', 'INV_1234567890'):
            with self.subTest(name=name):
                self.check(f'Your document {name} is ready.')

    def test_money_and_short_numbers_are_not_phones(self):
        for amount in ('1250000', '123456789', '12,50,000.00', '1250000000.00', '1,250,000,000.00'):
            with self.subTest(amount=amount):
                self.check(f'Your balance is {amount}.')

    def test_phone_digit_limits(self):
        self.assertEqual(reply_guard.phones('123456789'), set())
        self.assertEqual(reply_guard.phones('1234567890123456'), set())
        for number in ('1234567890', '123456789012345'):
            with self.subTest(number=number), self.assertRaises(reply_guard.ReplyBlocked):
                self.check(f'Call {number}.')

    def test_numeric_exclusions_do_not_hide_a_separate_foreign_phone(self):
        for value in ('29-10-2026', 'SINV-2026-000012', '1250000000.00'):
            with self.subTest(value=value), self.assertRaises(reply_guard.ReplyBlocked):
                self.check(f'{value} 9876543210')

    def test_own_evidence_allows_contacts_but_not_other_names_or_contacts(self):
        evidence = {'record_memory': 'Your alternate phone is +1 (555) 123-4567.',
                    'results': [{'email': 'own@example.test'}]}
        self.check('Call +1 555 123 4567 or OWN@example.test.', evidence=evidence)
        for text in ('Call 9876543210.', 'Email another@example.test.', 'Contact Other Retailer.'):
            with self.subTest(text=text), self.assertRaises(reply_guard.ReplyBlocked):
                self.check(text, evidence=evidence)

    def test_multiline_evidence_preserves_contact_boundaries(self):
        evidence = {'record_memory': 'Alternate phone:\n15551234567\nEmail:\nown@example.test',
                    'results': [{'phone': 9876543210}]}
        self.check('Call +1 (555) 123-4567 or 9876543210, email OWN@example.test.', evidence=evidence)
        self.assertEqual(reply_guard.contacts(evidence), ['15551234567', '9876543210', 'own@example.test'])

    def test_company_names_and_channel_company_are_allowed(self):
        for name in ('Local Company', 'Branch Company'):
            with self.subTest(name=name):
                self.check(f'Thank you for choosing {name}.')
        with self.assertRaises(reply_guard.ReplyBlocked):
            self.check('Branch Company works with Other Retailer.')

    def test_fixed_core_replies_are_exempt(self):
        from relay_core.ai.handoff import ACKNOWLEDGEMENT
        for text in (adapter.PRIVACY_REPLY, ACKNOWLEDGEMENT):
            self.skill.instructions = text
            self.check(text)
        self.f.get_all.assert_not_called()
        self.f.get_doc.assert_not_called()

    def test_absent_erpnext_tables_and_long_reply_have_bounded_queries(self):
        self.f.db.exists.return_value = False
        self.check('Hello there')
        self.f.get_all.assert_not_called()
        self.f.db.exists.return_value = True
        self.check(('Hello Customer ' * 130)[:2000])
        self.assertEqual(self.f.get_all.call_count, 3)

    def test_saved_event_note_quote_is_allowed_at_delivery(self):
        note = 'Our sale starts this weekend and all customers can enjoy special discounts on clothing.'
        self.f.db.get_value.return_value = 'Local Company'
        run = fixtures.Doc(ai_context=json.dumps({'events': [{'build': 'BUILD-1'}]}))
        message = fixtures.Doc(channel='CHANNEL-1', sender_endpoint=self.scope['endpoint'], relay_contact='SELF',
                               business_doctype='Customer', business_name='Acme Traders')
        reply_guard.check_delivery(run, self.skill, message, note)
        self.f.db.get_value.assert_called_once_with('Relay Channel', 'CHANNEL-1', 'company')

    def test_delivery_allows_incoming_and_saved_evidence_contacts_only(self):
        self.f.db.get_value.return_value = 'Local Company'
        run = fixtures.Doc(decision=json.dumps({'reply_contacts': ['15551234567', 'own@example.test']}))
        message = fixtures.Doc(channel='CHANNEL-1', sender_endpoint=self.scope['endpoint'], relay_contact='SELF',
            business_doctype='Customer', business_name='Acme Traders', content='Call 9876543210 or sender@example.test')
        for reply in ('Call +1 (555) 123-4567 or OWN@example.test.', 'Call 9876543210 or sender@example.test.'):
            with self.subTest(reply=reply):
                reply_guard.check_delivery(run, self.skill, message, reply)
        for reply in ('Call 9876543211.', 'Email other@example.test.', self.skill.instructions):
            with self.subTest(reply=reply), self.assertRaises(reply_guard.ReplyBlocked):
                reply_guard.check_delivery(run, self.skill, message, reply)


class GuardWiringTests(unittest.TestCase):
    def adapter_case(self):
        case = fixtures.SharedAdapterTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.skill.allowed_actions = '[{"action":"reply"}]'
        case.skill.execution_policy = 'Execute'
        from relay_core.ai.actions import REPLY
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))
        return case

    def test_adapter_allows_incoming_memory_and_event_quotes_through_delivery(self):
        case = self.adapter_case()
        note = 'Our sale starts this weekend and all customers can enjoy special discounts on clothing.'
        reply = 'Call +1 (555) 123-4567 or OWN@example.test.'
        for prompt, text in (({'incoming': reply}, reply),
                ({'incoming': 'Hi', 'reference_data': {'record_memory': reply}}, reply),
                ({'incoming': 'Hi', 'reference_data': {'events': [{'memory': note}]}}, note)):
            for tool in (False, True):
                with self.subTest(prompt=prompt, tool=tool):
                    calls = [dict(id='1', name='EXECUTE', arguments={'action': 'reply', 'parameters': {'text': text}})]
                    case.attempt.side_effect = ([case.outcome(calls=calls)] if tool else []) + [case.outcome(
                        dict(reply='' if tool else text, handoff=False, reason=''))]
                    result = case.adapter.complete(case.skill, 'partner', ('Supplier', 'SELF'), json.dumps(prompt))
                    self.assertFalse(result['handoff'])
                    self.assertEqual(result['actions'][0]['parameters']['text'], text)
                    run = fixtures.Doc(decision=json.dumps(result))
                    message = fixtures.Doc(channel='CHANNEL-1', sender_endpoint='sender@example.test',
                        business_doctype='Supplier', business_name='SELF', content=prompt['incoming'])
                    reply_guard.check_delivery(run, case.skill, message, text)

    def test_adapter_search_contacts_survive_saved_decision_and_delivery(self):
        case = self.adapter_case()
        reference = dict(name='supplier', report='configured_test_report', method='get_doc', doctype='Supplier', scope_field='name',
                         fields=['name', 'phone', 'email'])
        plan = dict(purpose='Read your contact details', reference='supplier', fields=reference['fields'],
                    arguments={'name': 'SELF'})
        call = dict(id='1', name='SEARCH', arguments={key: value for key, value in plan.items() if key != 'fields'})
        reply = 'Call +1 (555) 123-4567 or OWN@example.test.'
        with patch.object(case.adapter, 'contracts', return_value=[reference]), \
                patch.object(case.tools.Reader, '_read', return_value={
                    'name': 'SELF', 'phone': '+1 555 123 4567', 'email': 'own@example.test'}), \
                patch('relay_core.ai.service.authorize_search') as authorize:
            case.attempt.side_effect = [case.outcome(calls=[call]),
                case.outcome(dict(reply=reply, handoff=False, reason=''))]
            result = case.adapter.complete(case.skill, 'partner', ('Supplier', 'SELF'),
                                           '{"incoming":"My contact details?"}', search=plan)
        self.assertFalse(result['handoff'])
        self.assertEqual(len(result['reads']), 1)
        self.assertEqual(authorize.call_count, 2)
        self.assertEqual(result['reply_contacts'], ['15551234567', 'own@example.test'])
        message = fixtures.Doc(channel='CHANNEL-1', sender_endpoint='sender@example.test',
            business_doctype='Supplier', business_name='SELF', content='My contact details?')
        run = fixtures.Doc(decision=json.dumps(result))
        reply_guard.check_delivery(run, case.skill, message, reply)
        with self.assertRaises(reply_guard.ReplyBlocked):
            reply_guard.check_delivery(run, case.skill, message, 'Call 9876543210.')

    def test_history_and_skill_contact_details_do_not_authorize_a_reply(self):
        case = self.adapter_case()
        case.skill.instructions += ' Internal contact: secret@example.test, 9876543210.'
        for text in ('Email secret@example.test.', 'Call 9876543210.'):
            with self.subTest(text=text):
                case.attempt.return_value = case.outcome(dict(reply=text, handoff=False, reason=''))
                result = case.adapter.complete(case.skill, 'partner', ('Supplier', 'SELF'), json.dumps({
                    'incoming': 'Hi', 'history': [{'direction': 'Outgoing', 'content': text}]}))
                self.assertTrue(result['handoff'])
                self.assertEqual(result['reason'], reply_guard.REASON)

    def test_adapter_blocks_both_final_text_and_execute_text_before_actions(self):
        case = fixtures.SharedAdapterTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.skill.allowed_actions = '[{"action":"reply"}]'
        case.skill.execution_policy = 'Execute'
        from relay_core.ai.actions import REPLY
        with patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}):
            for tool in (False, True):
                calls = [dict(id='1', name='EXECUTE', arguments={'action': 'reply', 'parameters': {'text': 'secret@example.test'}})]
                case.attempt.side_effect = ([case.outcome(calls=calls)] if tool else []) + [case.outcome(
                    dict(reply='' if tool else 'secret@example.test', handoff=False, reason=''))]
                result = case.adapter.complete(case.skill, 'partner', ('Supplier', 'SELF'), '{"incoming":"Hi"}')
                self.assertTrue(result['handoff'])
                self.assertEqual(result['reason'], reply_guard.REASON)
                self.assertNotIn('actions', result)

    def test_delivery_guard_failure_hands_off_and_never_sends(self):
        case = fixtures.SkillDeliveryTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch.object(reply_guard, 'check_delivery', side_effect=reply_guard.ReplyBlocked()):
            case.service.process(case.run.name)
        case.send.assert_not_called()
        self.assertEqual(case.handoff.call_args.args[2], reply_guard.REASON)

    def test_dispatch_rechecks_prior_decision_and_all_channel_types(self):
        from relay_core.automation.service import outgoing_run
        for provider in ('WhatsApp', 'Telegram', 'Email'):
            message = fixtures.Doc(provider_context={'provider': provider})
            run = fixtures.Doc(name='RUN-1')
            with patch.object(service, 'delivery_scope'), patch.object(service, 'send_reply') as send, \
                    patch.object(reply_guard, 'check_delivery', side_effect=reply_guard.ReplyBlocked()):
                with self.assertRaises(reply_guard.ReplyBlocked):
                    service.dispatch_reply(run, fixtures.Doc(), message, 'secret@example.test', slot='event_reply_0')
            send.assert_not_called()
            self.assertIsNone(outgoing_run.get())
