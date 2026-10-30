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
    # Phrase boundaries keep business terms (agent commission, complaint number)
    # and Tamil negations out of the deterministic escalation path.
    person = r'(?:a |an |the |your )?(?:real |live )?(?:human|person|agent|staff(?: member)?|operator|representative|manager|supervisor)\b'
    request = r'(?:(?:talk|speak|chat) (?:to|with)|(?:connect|transfer) me (?:to|with)|hand (?:this|me) to) '
    value = ' '.join((text or '').casefold().split())
    # Remove only the negated clause, allowing a separate positive request.
    value = re.sub(r"\b(?:don’t|don't|do not|no need to) [^,;.!?]*", '', value)
    value = re.sub(r'\b(?:complaint|escalate|manager|staff|human)[^,;.!?]*\b(?:vendam|vendaam|venam|venumilla)\b', '', value)
    return bool(re.search(r'\b' + request + person, value)
                or re.search(r'\bi (?:want|need|would like) (?:to (?:talk|speak) to )?' + person
                             + r'(?=\s*(?:[.!?]|$)|\s+please\b)', value)
                or re.fullmatch(r'(?:please ' + person + '|' + person + r' please)[.!?]*', value)
                or re.search(r'\b(?:please escalate|escalate (?:this|my|the issue)|i (?:want|need|would like) to escalate)\b', value)
                or re.search(r'\b(?:i (?:want|need|would like) to (?:complain|(?:raise|file|make|lodge) a complaint)'
                             r'|i (?:have a complaint|am (?:unhappy|dissatisfied) with)|this is (?:a complaint|unacceptable))\b', value)
                or re.search(r'\b(?:manager|supervisor|staff|human|agent|aal|aalu|oruvar) '
                             r'(?:(?:kitta|kittae|kitte|kooda|oda) )?(?:pesanum|pesanumnu|pesavendum|pesunga|connect pannunga)\b', value)
                or re.search(r'\b(?:complaint|pugaar|pugar) (?:pannanum|pannum|pannuren|sollanum|irukku|kodukkanum)\b', value)
                or re.search(r'\bescalate (?:pannunga|pannanum|seiyunga)\b', value))


def human_reason(text):
    request = ' '.join((text or '').split())[:350]
    return f'Sender requested human review: {request}; escalation or complaint requires staff follow-up.'


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
    from relay_core.ai.language import incoming
    return incoming(message).strip()


def validate_result(value, names):
    """Require one finite score for every candidate, including rejected ones."""
    if (not isinstance(value, dict) or not {'scores', 'human_request'} <= set(value)
            or set(value) - {'scores', 'human_request', 'decline'}
            or type(value['human_request']) is not bool or type(value.get('decline', False)) is not bool):
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
    if value.get('decline') and winner:
        # Bind only a fixed Core decline to an accessible candidate; no skill tools run.
        return dict(selected=winner['id'], scores=scores, decline=True,
                    reason='Private or off-topic request', method='classifier')
    return dict(selected=selected, scores=scores, reason='Sender requested a person' if value['human_request']
                else 'Event matched' if selected else 'No confident event match', method='classifier')


def select(message, skills, run_id, deadline, *, history=None):
    from relay_core.ai.language import incoming
    from relay_core.ai.skills import is_default
    text = incoming(message)
    fallback = next((skill for skill in skills if is_default(skill)), None)
    skills = [skill for skill in skills if not is_default(skill)]
    if human_request(text):
        return dict(selected=None, scores=[], method='human', reason=human_reason(text))
    exact = [skill.name for skill in skills if skill.get('exact_trigger') and skill.exact_trigger == trigger(message)]
    if exact:
        return dict(selected=exact[0] if len(exact) == 1 else None, scores=[], method='exact',
                    reason='Exact event trigger' if len(exact) == 1 else 'Ambiguous exact event trigger')
    if not skills and fallback:
        return dict(selected=fallback.name, scores=[], method='default', reason='Default skill fallback')
    if not skills:
        return dict(selected=None, scores=[], method='none', reason='No enabled event')
    if len(text) > MAX_TEXT:
        raise ValueError('Message exceeds matching budget')
    from relay_core.ai.adapter import match
    from relay_core.automation.service import reserve_attempt
    # Matching is shared work; no candidate owns this inference.
    reserve_attempt(frappe._dict(name='matching:' + message.channel,
        daily_limit=sum(int(skill.daily_limit) for skill in skills)))
    value = match(skills[0].ai_model, [{'id': s.name, 'target': s.target} for s in skills],
                  text, run_id, deadline, **({'history': history} if history else {}))
    result = validate_result(value, {skill.name for skill in skills})
    if not result['selected']:
        result['reason'] = (human_reason(text) if value['human_request'] else
            'No confident event match for request: ' + ' '.join(text.split())[:350])
    if not result['selected'] and fallback and not value['human_request']:
        result.update(selected=fallback.name, method='default', reason='Default skill fallback')
    return result
