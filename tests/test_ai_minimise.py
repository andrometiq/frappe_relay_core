"""Contact details reach the model only as placeholders; old AI call payloads are blanked."""
import json
import sys
import time
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from frappe import _dict

import test_ai_skills as fixtures
import relay_core.automation.channel  # noqa: F401  Loads with the real framework before fixtures replace it.
from relay_core.ai import matching, memory

PHONE, EMAIL, NAME = '+91 98765 43210', 'ravi.kumar@example.test', 'Ravi Kumar'


def minimise(name=NAME):
    f = fixtures.framework()
    f.db.get_value.return_value = name
    return fixtures.module('relay_core/ai/minimise.py', f), f


class MaskTests(unittest.TestCase):
    def setUp(self):
        self.minimise, self.f = minimise()
        self.minimiser = self.minimise.Minimiser({'person': 'CONTACT-RAVI'})

    def test_mask_and_unmask_round_trip(self):
        value = {'incoming': f'I am ravi  kumar, call {PHONE} or mail {EMAIL}.',
                 'history': [{'content': f'{NAME} again: {EMAIL.upper()} / 919876543210'}],
                 'count': 3, 'none': None}
        masked = self.minimiser.mask(value)
        self.assertEqual(masked['incoming'], 'I am [PERSON_1], call [PHONE_1] or mail [EMAIL_1].')
        self.assertEqual(masked['history'][0]['content'], '[PERSON_1] again: [EMAIL_1] / [PHONE_1]')
        self.assertEqual((masked['count'], masked['none']), (3, None))
        self.assertEqual(self.minimiser.table, {'[PERSON_1]': 'ravi  kumar', '[PHONE_1]': PHONE, '[EMAIL_1]': EMAIL})
        self.assertEqual(self.minimiser.unmask(masked['incoming']), f'I am ravi  kumar, call {PHONE} or mail {EMAIL}.')
        self.assertEqual(self.minimiser.unmask('[PHONE_9] and [OTHER_1] stay'), '[PHONE_9] and [OTHER_1] stay')
        self.f.db.get_value.assert_called_once_with('Contact', 'CONTACT-RAVI', 'full_name')

    def test_dates_money_and_document_ids_stay_readable(self):
        text = 'Paid 1,25,000.50 on 2026-10-28 10:00 for SINV-2026-0000012345, ref 12345.'
        self.assertEqual(self.minimiser.mask(text), text)
        self.assertEqual(self.minimiser.table, {})

    def test_without_a_sender_only_emails_and_phones_are_masked(self):
        minimiser = self.minimise.Minimiser()
        self.assertEqual(minimiser.mask(f'{NAME} {PHONE} {EMAIL} +1 (555) 123-4567'),
                         f'{NAME} [PHONE_1] [EMAIL_1] [PHONE_2]')


class InferencePaths(unittest.TestCase):
    def test_reply_prompt_has_no_sender_contact_details_and_the_run_gets_the_table(self):
        case = fixtures.ConversationIdentityTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.message.content = f'This is Sim Sender. Call me on {PHONE} or write to {EMAIL}.'
        case.service.conversation_history = Mock(return_value=[{'direction': 'Incoming', 'content': 'sim sender here'}])
        complete = Mock(return_value={'handoff': False, 'reply': 'Noted', 'reads': []})
        with patch.dict(sys.modules, {'relay_core.ai.adapter': types.SimpleNamespace(complete=complete,
                                                                                     MAX_PROMPT_LENGTH=12000)}):
            decision = case.service.decide(case.skill, case.message)
        prompt = complete.call_args.args[3]
        for value in (PHONE, '9876543210', EMAIL, 'Sim Sender', 'sim sender'):
            self.assertNotIn(value, prompt)
        self.assertEqual(json.loads(prompt)['incoming'], 'This is [PERSON_1]. Call me on [PHONE_1] or write to [EMAIL_1].')
        self.assertIs(complete.call_args.kwargs['minimiser'].table, decision['minimise_table'])
        self.assertEqual(decision['minimise_table'],
                         {'[PERSON_1]': 'sim sender', '[PHONE_1]': PHONE, '[EMAIL_1]': EMAIL})

    def test_model_output_is_unmasked_before_the_reply_guard(self):
        case = fixtures.SharedAdapterTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.skill.update(allowed_actions='[{"action":"reply"}]', execution_policy='Execute')
        from relay_core.ai.actions import REPLY
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))
        module, _ = minimise()
        minimiser = module.Minimiser({'person': 'CONTACT-RAVI'})
        prompt = json.dumps(minimiser.mask({'incoming': f'{NAME} here, call {PHONE}'}))
        self.assertEqual(json.loads(prompt)['incoming'], '[PERSON_1] here, call [PHONE_1]')
        case.attempt.return_value = case.outcome(dict(reply='Sure [PERSON_1], we will call [PHONE_1].',
                                                      handoff=False, reason=''))
        result = case.adapter.complete(case.skill, 'partner', ('Supplier', 'SELF'), prompt, minimiser=minimiser)
        self.assertFalse(result['handoff'])
        self.assertEqual(result['actions'][0]['parameters']['text'], f'Sure {NAME}, we will call {PHONE}.')
        self.assertEqual(result['reply_contacts'], ['919876543210'])

    def test_matching_sends_masked_text_and_history(self):
        skill = _dict(name='one', target='Ledger', ai_model='model', daily_limit=1)
        lookup = Mock(**{'get_value.return_value': 'CONTACT-RAVI'})
        module, _ = minimise()
        with patch.object(matching.frappe, 'db', lookup), patch('relay_core.automation.service.reserve_attempt'), \
                patch.dict(sys.modules, {'relay_core.ai.minimise': module}), \
                patch('relay_core.ai.adapter.match', return_value={'scores': [{'id': 'one', 'score': .1}],
                                                                  'human_request': False}) as model:
            matching.select(_dict(content=f'{NAME}: ledger to {EMAIL}', channel='CH', relay_contact='R-1'), [skill],
                            'RUN-1', time.monotonic() + 20, history=[{'content': PHONE}])
        self.assertEqual(model.call_args.args[2], '[PERSON_1]: ledger to [EMAIL_1]')
        self.assertEqual(model.call_args.kwargs['history'], [{'content': '[PHONE_1]'}])
        lookup.get_value.assert_called_once_with('Relay Contact', 'R-1', 'contact')

    def test_memory_summary_masks_input_and_restores_lines(self):
        line = f'2026-10-28 10:00 | WhatsApp | A | Call {PHONE} | - | -'
        def model(name, prompt, **kw):
            self.assertNotIn(PHONE, prompt)
            return {'lines': json.loads(prompt)['new_events']}
        with patch.object(memory, 'complete_json', side_effect=model):
            self.assertEqual(memory.summarize('Summary Model', '', [line], ('Customer', 'C1')), line)


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.minimise, self.f = minimise()
        self.minimise.now_datetime = lambda: datetime(2026, 10, 30, 12)
        payload = dict(request_payload='{"prompt": "x"}', response_payload='{}', raw_response='x')
        self.rows = [_dict(name='OLD', reference_doctype='Relay Automation Run', creation=datetime(2026, 9, 1), **payload),
                     _dict(name='NEW', reference_doctype='Relay Automation Run', creation=datetime(2026, 10, 29), **payload),
                     _dict(name='OTHER', reference_doctype='Document AI Extraction', creation=datetime(2026, 9, 1), **payload)]
        def set_value(doctype, filters, values, update_modified):
            self.assertEqual((doctype, update_modified), ('Document AI Call Log', False))
            self.assertEqual(filters['request_payload'], ['is', 'set'])
            for row in self.rows:
                if (row.reference_doctype == filters['reference_doctype'] and row.request_payload
                        and row.creation < filters['creation'][1] and filters['creation'][0] == '<'):
                    row.update(values)
        self.f.db.set_value.side_effect = set_value

    def test_purge_blanks_only_old_automation_run_payloads(self):
        self.f.db.get_single_value.return_value = 30
        self.minimise.purge_ai_payloads()
        self.f.db.get_single_value.assert_called_once_with('Relay Settings', 'ai_log_retention_days')
        old, new, other = self.rows
        self.assertEqual((old.request_payload, old.response_payload, old.raw_response), ('', '', ''))
        self.assertEqual(new.request_payload, '{"prompt": "x"}')
        self.assertEqual(other.request_payload, '{"prompt": "x"}')

    def test_empty_retention_uses_thirty_days(self):
        self.f.db.get_single_value.return_value = 0
        self.minimise.purge_ai_payloads()
        self.assertEqual(self.f.db.set_value.call_args.args[1]['creation'], ['<', datetime(2026, 9, 30, 12)])


if __name__ == '__main__':
    unittest.main()
