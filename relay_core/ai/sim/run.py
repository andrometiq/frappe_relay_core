"""Harness entry: `bench --site relay-ai-test.local execute relay_core.ai.sim.run.main --kwargs "{'suite': 'core'}"`."""
import json
import pathlib
import subprocess
import time
from collections import Counter
from contextlib import contextmanager

import frappe

from relay_core.ai.sim import checks, report, scenarios
from relay_core.ai.sim.driver import Driver
from relay_core.ai.sim.fake_provider import FakeProvider, ReplayStore, Script
from relay_core.ai.sim.seed import ADAPTERS, MANAGER, OTHER_CUSTOMER, STAFF, guard, seed

TIERS = ('fake', 'replay', 'live')
WATCHED = ('Company', 'Customer', 'Supplier', 'Contact', 'User', 'GL Entry', 'Journal Entry', 'Payment Entry')
RUNTIME = pathlib.Path(__file__).resolve().parents[3] / '.runtime' / 'sim'
REPLAYS = RUNTIME / 'replays'


class TierRefused(RuntimeError):
    """A tier's isolation precondition is not met."""


def main(suite: str = 'core', tier: str = 'fake', k: int = 1, scenario: str | None = None,
         spend_cap_usd: float | None = None) -> dict:
    """Seed, run each scenario k times (all trials must pass), write the report; exit 1 on a gated failure."""
    site = guard()
    if tier not in TIERS:
        raise TierRefused(f'Unknown tier {tier}')
    seeded = seed([suite])
    if 'skipped' in seeded['suites'].get(suite, {}):
        return {'suite': suite, 'skipped': seeded['suites'][suite]['skipped']}
    rows = [scenarios.resolve(row, tokens(row, seeded)) for row in scenarios.load_suite(suite)
            if scenario in (None, row['id'])]
    with answers_for(tier, suite, rows, spend_cap_usd) as answers:
        results = [run_scenario(row, int(k), seeded, answers) for row in rows]
    built = report.build(suite=suite, tier=tier, site=site, k=int(k), results=results, commits=commits(suite),
                         capabilities=capability_hashes())
    paths = report.write(built, RUNTIME, time.strftime('%Y%m%d-%H%M%S'))
    code = report.exit_code(built)
    print(json.dumps({'summary': built['summary'], 'report': [str(path) for path in paths]}, ensure_ascii=False))
    if code:
        raise SystemExit(code)
    return built['summary']


def tokens(row: dict, seeded: dict) -> dict[str, str]:
    """`{business}` is the persona's own record; `{other}` is a record of someone else of the same type."""
    own = seeded['personas'][row['persona']]['business']
    others = [value['business'][1] for ref, value in seeded['personas'].items()
              if ref != row['persona'] and value['business'][0] == own[0]]
    other = OTHER_CUSTOMER if own[0] == 'Customer' else others[0]
    return {'business': own[1], 'other': other}


@contextmanager
def answers_for(tier: str, suite: str, rows: list[dict], spend_cap_usd: float | None):
    if tier == 'live':
        live_ready(spend_cap_usd)
        raise NotImplementedError('The live tier and its judge arrive in build step 13')
    answers = Script(rows) if tier == 'fake' else ReplayStore(REPLAYS / f'{suite}.json', capability_hashes())
    with FakeProvider(answers):
        yield answers


def live_ready(spend_cap_usd: float | None) -> None:
    """Live calls need a test site, test mode and a monthly cap no higher than the run's own cap."""
    guard()
    settings = frappe.get_single('Relay Settings')
    cap = float(settings.monthly_spend_cap_usd or 0)
    if not spend_cap_usd or float(spend_cap_usd) <= 0:
        raise TierRefused('The live tier needs spend_cap_usd')
    if not settings.test_mode or not 0 < cap <= float(spend_cap_usd):
        raise TierRefused('The live tier needs test mode and a Relay Settings monthly cap within spend_cap_usd')


def run_scenario(row: dict, k: int, seeded: dict, answers) -> dict:
    started, failed, cost = time.monotonic(), [], 0.0
    state = {}
    for trial in range(k):
        trial_failed, trial_cost, state = run_trial(row, seeded, answers)
        failed += [dict(item, trial=trial + 1) for item in trial_failed]
        cost += trial_cost
    return {'id': row['id'], 'language': row['language'], 'safety': scenarios.is_safety(row), 'passed': not failed,
            'trials': k, 'failed_checks': failed, 'state_diff': state, 'cost_usd': round(cost, 6),
            'seconds': round(time.monotonic() - started, 2)}


def run_trial(row: dict, seeded: dict, answers) -> tuple[list[dict], float, dict]:
    context = {'scenario': row, 'seed': seeded, 'persona': row['persona'],
               'business': seeded['personas'][row['persona']]['business'], 'driver': Driver(), 'undo': [],
               'disclosures': Counter(), 'run': None}
    failures, cost, state = [], 0.0, {}
    try:
        for index, turn in enumerate(row['turns']):
            before, calls = snapshot(), len(answers.calls)
            if 'step' in turn:
                STEPS[turn['step']](context, **turn.get('args', {}))
                identifier = None
            else:
                if isinstance(answers, Script):
                    answers.cue(row['id'], index)
                identifier = context['driver'].post_inbound(row, turn)
            context['driver'].drain()
            if 'expect' not in turn:
                continue
            observation = observe(context, identifier, before, answers.calls[calls:])
            observation['expected_inserts'] = expected_inserts(turn['expect'])
            oracle = turn['expect'].get('oracle')
            context['oracle_text'] = frappe.get_attr(oracle)(seeded, row) if oracle else None
            failures += [dict(item, turn=index + 1) for item in checks.run_checks(observation, turn['expect'], context)]
            cost, state = cost + observation['calls']['usd'], observation['state']
    finally:
        for undo in reversed(context['undo']):
            undo()
        frappe.db.commit()
    return failures, cost, state


def snapshot() -> dict:
    tables = [doctype for doctype in WATCHED if frappe.db.table_exists(doctype)]
    return {doctype: list(frappe.db.sql(f'select count(*), max(modified) from `tab{doctype}`')[0]) for doctype in tables}


def observe(context: dict, identifier: str | None, before: dict, calls: list[dict]) -> dict:
    if identifier:
        message = frappe.db.get_value('Relay Message', {'provider_id': identifier},
                                      ['name', 'business_doctype', 'business_name'], as_dict=True)
        context['run'] = message and frappe.db.get_value('Relay Automation Run', {'message': message.name},
            ['name', 'status', 'stage', 'decision', 'reason', 'ticket', 'skill'], as_dict=True)
        context['message'] = message
    run, message = context['run'] or {}, context.get('message') or {}
    decision = json.loads(run.get('decision') or '{}') if run else {}
    outbound = context['driver'].outbound()
    for row in outbound:
        if row['slot'] == 'disclosure':
            context['disclosures'][run.get('ticket')] += 1
    logs = frappe.get_all('Document AI Call Log', filters={'reference_doctype': 'Relay Automation Run',
                          'reference_name': run.get('name')}, pluck='cost_usd') if run else []
    business = [message.get('business_doctype'), message.get('business_name')]
    return {'run': dict(run, decision=decision), 'outbound': outbound,
            'tool_calls': [call for row in calls for call in row['tool_calls']],
            'reads': [{'capability': row.get('tool'), 'business': business} for row in decision.get('reads', [])],
            'journals': frappe.get_all('Relay Flow Action', filters={'automation_run': run.get('name')},
                fields=['name', 'action', 'status', 'capability_hash', 'expires_on']) if run else [],
            'calls': {'count': len(logs), 'usd': float(sum(value or 0 for value in logs))},
            'state': checks.diff(before, snapshot()), 'disclosures': dict(context['disclosures']),
            'skill_actions': skill_actions(run.get('skill'))}


def skill_actions(skill: str | None) -> list[str]:
    if not skill:
        return []
    return [row['action'] for row in json.loads(frappe.db.get_value('Relay AI Skill', skill, 'allowed_actions') or '[]')]


def expected_inserts(expect: dict) -> dict:
    return {doctype: frappe.db.count(doctype, filters)
            for doctype, filters in (expect.get('state') or {}).get('inserted', [])}


def awaiting(context: dict) -> dict:
    return frappe.get_all('Relay Flow Action', filters={'automation_run': context['run']['name'], 'status': 'Awaiting approval'},
                          fields=['name', 'input_hash', 'scope_fingerprint'], limit=1)[0]


@contextmanager
def acting_as(user: str):
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)


def step_takeover(context: dict) -> None:
    from relay_core.tickets import claim
    with acting_as(STAFF):
        claim(context['run']['ticket'])
    frappe.db.commit()


def step_approve(context: dict) -> None:
    from relay_core.flows.actions import approve
    row = awaiting(context)
    with acting_as(MANAGER):
        approve(row.name, row.input_hash, row.scope_fingerprint)
    frappe.db.commit()


def step_reject(context: dict, reason: str = 'Staff declined the request') -> None:
    from relay_core.flows.actions import reject
    with acting_as(MANAGER):
        reject(awaiting(context).name, reason)
    frappe.db.commit()


def step_expire(context: dict) -> None:
    from relay_core.flows.actions import expire_approvals
    frappe.db.set_value('Relay Flow Action', awaiting(context).name, 'expires_on', '2000-01-01 00:00:00')
    expire_approvals()
    frappe.db.commit()


def step_disable_capability(context: dict, key: str) -> None:
    switch(context, 'Relay AI Capability', key, 'enabled', 0)


def step_disable_user(context: dict) -> None:
    login = context['seed']['personas'][context['persona']]['user']
    if not login:
        raise ValueError(f"{context['persona']} has no login to disable")
    switch(context, 'User', login, 'enabled', 0)


def step_spend_cap(context: dict, usd: float, skill: str) -> None:
    switch(context, 'Relay AI Skill', frappe.db.get_value('Relay AI Skill', {'title': skill}), 'daily_spend_cap_usd', usd)


def step_duplicate_callback(context: dict) -> None:
    context['driver'].repeat_last()


def switch(context: dict, doctype: str, name: str, field: str, value) -> None:
    """Set one value for this trial and register its restore."""
    old = frappe.db.get_value(doctype, name, field)
    frappe.db.set_value(doctype, name, field, value)
    frappe.db.commit()
    context['undo'].append(lambda: frappe.db.set_value(doctype, name, field, old))


STEPS = {'takeover': step_takeover, 'approve': step_approve, 'reject': step_reject, 'expire': step_expire,
         'disable_capability': step_disable_capability, 'disable_user': step_disable_user,
         'spend_cap': step_spend_cap, 'duplicate_callback': step_duplicate_callback}


def capability_hashes() -> dict:
    return dict(frappe.get_all('Relay AI Capability', fields=['name', 'current_hash'], as_list=True))


def commits(suite: str) -> dict:
    def head(app: str) -> str | None:
        try:
            path = frappe.get_app_path(app)
            return subprocess.run(['git', '-C', path, 'rev-parse', '--short', 'HEAD'], capture_output=True,
                                  text=True, timeout=10).stdout.strip() or None
        except (ImportError, OSError, subprocess.SubprocessError):
            return None
    return {'core': head('relay_core'), 'adapter': head(ADAPTERS[suite]) if suite in ADAPTERS else None}
