"""AI spend caps: reserve before every provider call, settle from usage, refuse past a cap."""
import json
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import test_ai_skills as fixtures
import relay_core.tickets  # noqa: F401  Patched by the run fixture, so it must load with the real framework.

MONTH, DAY = 'test.local|relay-ai-spend:test.local:2026-10', 'test.local|relay-ai-spend:Sim Skill:2026-10-30'


class BudgetMath(unittest.TestCase):
    def setUp(self):
        self.spend = fixtures.spend_budget(self)
        self.budget = sys.modules['relay_core.ai.budget']
        self.model = fixtures.Doc(name='MODEL-1', cost_per_m_input=3, cost_per_m_output=15)
        self.skill = fixtures.Doc(name='Sim Skill', daily_spend_cap_usd=2)

    def test_reservation_then_settle_replaces_the_estimate_with_the_actual_cost(self):
        estimate = self.budget.estimate_usd(self.model, 4000, 1000)
        self.assertAlmostEqual(estimate, 1000 * 3 / 1e6 + 1000 * 15 / 1e6)
        reservation = self.budget.reserve(self.skill, estimate)
        self.assertEqual(reservation, {'keys': [MONTH, DAY], 'estimate': estimate, 'charged': estimate})
        self.assertAlmostEqual(self.spend.cache.values[MONTH], estimate)
        actual = self.budget.actual_usd(self.model, {'prompt_tokens': 800, 'completion_tokens': 100})
        self.assertAlmostEqual(actual, 800 * 3 / 1e6 + 100 * 15 / 1e6)
        self.budget.settle(reservation, actual)
        self.assertAlmostEqual(self.spend.cache.values[MONTH], actual)
        self.assertAlmostEqual(self.spend.cache.values[DAY], actual)
        self.assertEqual(self.budget.actual_usd(self.model, {'cost': 0.25, 'prompt_tokens': 10 ** 6}), 0.25)
        self.budget.refund(reservation)  # A turn handed to the AI service is charged again when its run replays it.
        self.assertAlmostEqual(self.spend.cache.values[MONTH], 0)
        self.assertAlmostEqual(self.spend.cache.values[DAY], 0)

    def test_missing_model_rates_raise(self):
        for rates in ({'cost_per_m_input': 0, 'cost_per_m_output': 15}, {'cost_per_m_input': 3, 'cost_per_m_output': None}):
            with self.subTest(rates=rates), self.assertRaisesRegex(ValueError, 'MODEL-1 needs input and output costs'):
                self.budget.estimate_usd(fixtures.Doc(self.model, **rates), 100, 100)

    def test_a_refused_reservation_leaves_both_totals_unchanged(self):
        self.budget.reserve(self.skill, 1.5)
        with self.assertRaisesRegex(ValueError, '^AI spend cap reached$'):
            self.budget.reserve(self.skill, 1)
        self.assertEqual(self.spend.cache.values, {MONTH: 1.5, DAY: 1.5})
        self.budget.reserve(fixtures.Doc(name='Other Skill'), 1)  # Its own day; empty cap uses 2.
        self.assertEqual(self.spend.cache.values[MONTH], 2.5)

    def test_concurrent_reservations_cannot_pass_the_cap(self):
        accepted, start = [], threading.Barrier(40)
        def reserve():
            start.wait()
            try:
                accepted.append(self.budget.reserve(self.skill, 0.15))
            except ValueError:
                pass
        threads = [threading.Thread(target=reserve) for _ in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertLessEqual(len(accepted), 13)
        self.assertGreater(len(accepted), 0)
        self.assertAlmostEqual(self.spend.cache.values[DAY], 0.15 * len(accepted))
        self.assertLessEqual(self.spend.cache.values[DAY], 2)


class ProviderCallCaps(unittest.TestCase):
    """Each adapter entry point reserves before the provider call and refuses at a cap."""
    def setUp(self):
        self.case = fixtures.SharedAdapterTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.skill.update(name='Sim Skill', daily_spend_cap_usd=2)
        self.cache = self.case.spend.cache.values

    def complete(self):
        return self.case.adapter.complete(self.case.skill, 'partner', ('Supplier', 'SUP-A'), 'Question', 'RUN-1')

    def test_complete_settles_from_usage(self):
        outcome = self.case.outcome({'reply': '', 'handoff': True, 'reason': 'Staff assistance required'})
        outcome['result']['usage'] = {'prompt_tokens': 1000, 'completion_tokens': 100}
        self.case.attempt.return_value = outcome
        self.assertTrue(self.complete()['handoff'])
        self.assertAlmostEqual(self.cache[MONTH], 1000 * 1 / 1e6 + 100 * 2 / 1e6)
        self.assertAlmostEqual(self.cache[DAY], self.cache[MONTH])

    def test_failed_provider_call_keeps_the_reserved_estimate(self):
        self.case.attempt.return_value = {'ok': False, 'error': 'Service unavailable'}
        with self.assertRaises(ValueError):
            self.complete()
        self.assertGreater(self.cache[MONTH], 0)

    def test_monthly_cap_stops_every_entry_point_before_the_provider_call(self):
        import time
        self.case.spend.db.get_single_value.return_value = 0.0001
        calls = (self.complete,
                 lambda: self.case.adapter.complete_json('MODEL-1', 'Draft knowledge'),
                 lambda: self.case.adapter.match('MODEL-1', [], 'Question', 'RUN-1', time.monotonic() + 20),
                 lambda: self.case.adapter.observe_image(self.case.skill, [{'data': b'image', 'mime': 'image/png'}]))
        with patch('relay_core.automation.multimodal.image_input', return_value={'data': b'image', 'mime': 'image/png'}):
            for call in calls:
                with self.subTest(call=call), self.assertRaisesRegex(ValueError, '^AI spend cap reached$'):
                    call()
        self.case.attempt.assert_not_called()
        self.assertTrue(all(value == 0 for value in self.cache.values()))

    def test_daily_skill_cap_stops_the_reply_before_the_provider_call(self):
        self.case.skill.daily_spend_cap_usd = 0.0001
        with self.assertRaisesRegex(ValueError, '^AI spend cap reached$'):
            self.complete()
        self.case.attempt.assert_not_called()
        self.assertEqual(self.cache, {MONTH: 0, DAY: 0})

    def test_model_without_rates_never_calls_the_provider(self):
        self.case.model.cost_per_m_output = 0
        with self.assertRaisesRegex(ValueError, 'needs input and output costs'):
            self.complete()
        self.case.attempt.assert_not_called()


class RunHandoff(unittest.TestCase):
    def setUp(self):
        from test_ai_actions import VerifiedContactExecution
        VerifiedContactExecution.setUp(self)
        self.run.decision = None

    def test_cap_hit_hands_the_run_to_staff(self):
        self.service.decide = Mock(side_effect=ValueError('AI spend cap reached'))
        self.service.process(self.run.name)
        self.handoff.assert_called_once()
        self.assertEqual(self.handoff.call_args.args[2], 'AI spend cap reached')
        self.send.assert_not_called()

    def test_run_stores_the_minimise_table(self):
        decision = dict(reply='', handoff=True, reason='Staff needed', user='partner', reads=[])
        self.service.decide = Mock(return_value=dict(decision, minimise_table={'[PHONE_1]': '+91 98765 43210'}))
        self.service.process(self.run.name)
        self.assertEqual(json.loads(self.run.minimise_table), {'[PHONE_1]': '+91 98765 43210'})
        self.assertNotIn('minimise_table', json.loads(self.run.decision))


if __name__ == '__main__':
    unittest.main()
