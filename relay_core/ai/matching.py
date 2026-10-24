"""Bounded event selection. Classifier output grants no business-data access."""
import math
import re
from decimal import Decimal

import frappe

MAX_CANDIDATES = 20
MAX_TEXT = 4000


def candidates(message):
    from relay_core.business_access import reference
    business = reference(message)
    if not business:
        return []
    names = frappe.get_all('Relay AI Skill', filters={'channel': message.channel,
        'business_doctype': business[0], 'enabled': 1}, pluck='name',
        order_by='name asc', limit_page_length=MAX_CANDIDATES + 1)
    if len(names) > MAX_CANDIDATES:
        raise ValueError('Too many enabled events for bounded matching')
    return [frappe.get_doc('Relay AI Skill', name) for name in names]


def human_request(text):
    return bool(re.search(r'\b(?:human|person|agent|staff|operator)\b', (text or '').casefold()))


def trigger(message):
    from relay_core.automation.provenance import context_of
    context = context_of(message)
    if context.get('original_message_type') == 'button':
        import json
        data = message.get('message_data') or {}
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict) and data.get('selection_type') == 'template_button':
            return data.get('selection_id')
    return (message.content or '').strip()


def validate_result(value, names):
    """Require one finite score for every candidate, including rejected ones."""
    if not isinstance(value, dict) or set(value) != {'scores', 'human_request'} or type(value['human_request']) is not bool:
        raise ValueError('Invalid event match')
    scores = value['scores']
    if not isinstance(scores, list) or len(scores) != len(names):
        raise ValueError('Invalid event scores')
    seen = set()
    for row in scores:
        if (not isinstance(row, dict) or set(row) != {'id', 'score'}
                or not isinstance(row['id'], str) or row['id'] not in names or row['id'] in seen
                or type(row['score']) not in (int, float) or not math.isfinite(row['score'])
                or not 0 <= row['score'] <= 1):
            raise ValueError('Invalid event score')
        seen.add(row['id'])
    ranked = sorted(scores, key=lambda row: row['score'], reverse=True)
    winner = ranked[0] if ranked else None
    runner = ranked[1]['score'] if len(ranked) > 1 else 0
    selected = None
    if (winner and not value['human_request'] and Decimal(str(winner['score'])) >= Decimal('0.85')
            and Decimal(str(winner['score'])) - Decimal(str(runner)) >= Decimal('0.15')):
        selected = winner['id']
    return dict(selected=selected, scores=scores, reason='Sender requested a person' if value['human_request']
                else 'Event matched' if selected else 'No confident event match', method='classifier')


def select(message, skills, run_id, deadline, *, history=None):
    if human_request(message.content):
        return dict(selected=None, scores=[], method='human', reason='Sender requested a person')
    exact = [skill.name for skill in skills if skill.get('exact_trigger') and skill.exact_trigger == trigger(message)]
    if exact:
        return dict(selected=exact[0] if len(exact) == 1 else None, scores=[], method='exact',
                    reason='Exact event trigger' if len(exact) == 1 else 'Ambiguous exact event trigger')
    if not skills:
        return dict(selected=None, scores=[], method='none', reason='No enabled event')
    if len(message.content or '') > MAX_TEXT:
        raise ValueError('Message exceeds matching budget')
    from relay_core.ai.adapter import match
    from relay_core.automation.service import reserve_attempt
    # Matching is shared work; no candidate owns this inference.
    reserve_attempt(frappe._dict(name='matching:' + message.channel,
        daily_limit=sum(int(skill.daily_limit) for skill in skills)))
    value = match(skills[0].ai_model, [{'id': s.name, 'target': s.target} for s in skills],
                  message.content or '', run_id, deadline, **({'history': history} if history else {}))
    return validate_result(value, {skill.name for skill in skills})
