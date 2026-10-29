"""Repeatable customer decision checks, without operational messages or runs."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import frappe
from relay_core.business_access import document_name


def load_cases(cases):
    if cases is None:
        cases = json.loads(Path(__file__).with_name('cases.json').read_text())
    elif isinstance(cases, str):
        cases = json.loads(cases)
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError('Provide 1–50 eval cases')
    for case in cases:
        if (not isinstance(case, dict) or set(case) - {'message', 'history', 'expected', 'must_contain', 'must_not_contain'}
                or not isinstance(case.get('message'), str) or not 1 <= len(case['message']) <= 4000):
            raise ValueError('Each eval case needs a message of 1–4000 characters')
        expected = case.get('expected')
        expected = [expected] if isinstance(expected, str) else expected
        if not isinstance(expected, list) or not expected or any(item not in ('reply', 'handoff', 'decline') for item in expected):
            raise ValueError('Expected must be reply, handoff, decline or a list of these')
        history = case.get('history', [])
        if not isinstance(history, list) or len(history) > 6:
            raise ValueError('Provide at most six history entries')
        for row in history:
            if (not isinstance(row, dict) or set(row) != {'direction', 'content'}
                    or row['direction'] not in ('Incoming', 'Outgoing')
                    or not isinstance(row['content'], str) or not 1 <= len(row['content']) <= 2000):
                raise ValueError('History needs Incoming/Outgoing direction and content')
        for key in ('must_contain', 'must_not_contain'):
            values = case.get(key, [])
            if (not isinstance(values, list) or len(values) > 20
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 200 for value in values)):
                raise ValueError(f'{key} needs at most 20 non-empty strings of up to 200 characters')
    return cases


def grade(case, decision):
    from relay_core.ai.adapter import PRIVACY_REPLY
    from relay_core.ai.handoff import ACKNOWLEDGEMENT
    from relay_core.flows.actions import definitions
    outcome = 'decline' if decision.get('decline') else 'handoff' if decision.get('handoff') else 'reply'
    if outcome == 'decline':
        reply = PRIVACY_REPLY
    elif outcome == 'handoff':
        reply = ACKNOWLEDGEMENT
    else:
        registered = definitions() if decision.get('actions') else {}
        reply = '\n'.join([decision.get('reply', ''), *(row['parameters']['text']
            for row in decision.get('actions', []) if registered[row['action']]['effect'] == 'reply')]).strip()
    expected = case['expected'] if isinstance(case['expected'], list) else [case['expected']]
    reasons = []
    if outcome not in expected:
        reasons.append(f'Expected {" or ".join(expected)}, got {outcome}')
    if outcome == 'reply' and not reply:
        reasons.append('No customer reply; decision only proposed a search or action')
    for value in case.get('must_contain', []):
        if value.casefold() not in reply.casefold():
            reasons.append(f'Missing required text: {value}')
    for value in case.get('must_not_contain', []):
        if value.casefold() in reply.casefold():
            reasons.append(f'Contains forbidden text: {value}')
    return dict(passed=not reasons, outcome=outcome, reply=reply,
                reason='; '.join(reasons) if reasons else 'Matched expected outcome and text checks')


@frappe.whitelist(methods=['POST'])
def run(skill, model=None, cases=None, allow_live=False):
    """Run saved cases through the same text decision used by decide(), with normal AI call logs.

    POST relay_core.ai.evals.run with skill, optional model/cases (list or JSON).
    Bench: bench --site X execute relay_core.ai.evals.run_cli --kwargs '{"skill":"Support"}'
    Requires System Manager/Relay Communication Manager and skill write access. Test mode
    must be enabled unless allow_live=true (or 1) explicitly permits paid live model calls;
    this does not bypass the existing test-mode network restrictions.

    Cases contain message, optional history [{direction: Incoming|Outgoing, content: ...}],
    expected (reply|handoff|decline, or a list of acceptable classes), optional must_contain
    and must_not_contain string lists (case-insensitive). At most 50 cases per call.
    Identity is synthetic: Customer/Supplier EVAL-SELF, endpoint sender@eval.invalid.
    No saved conversation, memory or event data is loaded. Searches/actions are proposals
    only: there is no run ID, execution, message, ticket, enqueue or send. AI call logs are
    the only intended writes. Model overrides never save the skill. Errors fail the case.
    This checks first-turn policy, not completed multi-step searches or business execution.
    """
    if model is not None and model != "":
        document_name(model)
    document_name(skill)
    from relay_core.permissions import MANAGER, require_access
    from relay_core.test_mode import is_enabled
    from relay_core.ai.service import decide_text
    if not {MANAGER, 'System Manager'}.intersection(frappe.get_roles()):
        raise frappe.PermissionError('AI evals require a manager role')
    require_access('Relay AI Skill', 'write')
    if allow_live not in (False, True, 0, 1, '0', '1'):
        raise ValueError('allow_live must be a boolean or 0/1')
    if not is_enabled() and allow_live not in (True, 1, '1'):
        raise ValueError('Enable test mode or explicitly set allow_live=true to run AI evals')
    cases = load_cases(cases)
    saved = frappe.get_doc('Relay AI Skill', skill)
    saved.check_permission('write')
    selected = copy.copy(saved)
    if model:
        frappe.get_doc('AI Model', model).check_permission('read')
        selected.ai_model = model
    business = (selected.business_doctype, 'EVAL-SELF')
    scope = dict(provider='Email', endpoint='sender@eval.invalid', company=None, business=list(business))
    results = []
    for index, case in enumerate(cases, 1):
        try:
            decision = decide_text(selected, case['message'], selected.run_as_user, business, scope,
                                   copy.deepcopy(case.get('history', [])))
            result = grade(case, decision)
        except Exception as error:
            # Provider errors can contain private payloads; expose only the error class.
            result = dict(passed=False, outcome='error', reply='', reason=f'Decision failed: {type(error).__name__}')
        results.append(dict(index=index, message=case['message'], expected=case['expected'], **result))
    passed = sum(row['passed'] for row in results)
    return dict(skill=saved.name, skill_version=str(saved.modified), model=selected.ai_model,
                timestamp=datetime.now(timezone.utc).isoformat(), cases=results,
                summary=dict(total=len(results), passed=passed, failed=len(results) - passed))


def run_cli(skill, model=None, cases=None, allow_live=False):
    """Bench entry; accepts the same arguments and permissions as run()."""
    return run(skill, model=model, cases=cases, allow_live=allow_live)
