"""Poll campaigns. A tap on the template's opt-in button asks the campaign question; the person picks an option, then
confirms or changes it. A tap on the opt-out button opts the number out. No AI, flow or ticket handles these taps."""
import json
import re

import frappe
from frappe import _dict
from frappe.utils import cint

from relay_core import polls
from relay_core.automation.contracts import canonical
from relay_core.message_types import text

RECIPIENT = 'Relay Campaign Recipient'
# A choice value names its recipient row, so a tap finds its poll without a lookup of the sent message.
CHOICE = re.compile(r'cpoll:([\w-]+):(\d+|confirm:\d+|change)')
THANKS = 'Thank you, your response is recorded.'
ALREADY = 'Your response is already recorded. Thank you.'
CONFIRMED, CHOSEN, ASKED, OPTED_OUT = 'Confirmed', 'Chosen', 'Asked', 'Opted out'


def template_buttons(snapshot: dict) -> list[str]:
    """Quick reply button texts of the campaign template."""
    for component in snapshot.get('template', {}).get('components') or []:
        if str(component.get('type') or '').upper() == 'BUTTONS':
            return [button.get('text') for button in component.get('buttons') or []
                    if str(button.get('type') or '').upper() == 'QUICK_REPLY' and button.get('text')]
    return []


def settings(snapshot: dict, data: dict) -> dict:
    """The checked poll set-up: question, options, the opt-in and optional opt-out button and the thank-you text."""
    if not isinstance(data, dict) or set(data) - {'question', 'options', 'opt_in', 'opt_out', 'thanks'}:
        raise ValueError('Invalid poll settings')
    buttons = template_buttons(snapshot)
    if not buttons:
        raise ValueError('Choose a template with a quick reply button')
    opt_in, opt_out = data.get('opt_in'), data.get('opt_out') or ''
    if opt_in not in buttons:
        raise ValueError('Choose the template button that opens the poll')
    if opt_out and (opt_out not in buttons or opt_out == opt_in):
        raise ValueError('Choose another template button for opt-out, or none')
    _, content = polls.prepare({'question': data.get('question'), 'options': data.get('options')})
    return {**{key: content['poll'][key] for key in ('question', 'options')}, 'opt_in': opt_in, 'opt_out': opt_out,
            'thanks': text(data.get('thanks') or THANKS, 1024).strip() or THANKS}


def is_ready(snapshot: dict) -> bool:
    return 'poll' not in snapshot or bool(snapshot['poll'].get('question'))


@frappe.whitelist(methods=['POST'])
def configure(name, poll):
    """Save the poll set-up of a Draft poll campaign."""
    from relay_core.bulk_campaigns import bulk, lock_campaign, read
    from relay_core.automation.service import internal_save
    lock_campaign(name)
    doc = bulk(name, ('Draft',))
    snapshot = json.loads(doc.arguments)
    if 'poll' not in snapshot:
        frappe.throw('This is not a poll campaign')
    try:
        snapshot['poll'] = settings(snapshot, frappe.parse_json(poll))
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.arguments = canonical(snapshot)
    internal_save(doc)
    return read(name)


@frappe.whitelist(methods=['POST'])
def close(name):
    """Stop a poll campaign taking answers. Its taps are no longer claimed, so the usual automation and AI answer them."""
    from relay_core.bulk_campaigns import bulk, lock_campaign, read
    from relay_core.automation.service import internal_save
    lock_campaign(name)
    doc = bulk(name)
    snapshot = json.loads(doc.arguments)
    if not snapshot.get('poll', {}).get('question'):
        frappe.throw('This is not a poll campaign')
    snapshot['poll']['closed'] = 1
    doc.arguments = canonical(snapshot)
    internal_save(doc)
    return read(name)


def summary(name: str, snapshot: dict) -> dict:
    """The poll set-up with its counts: per option confirmed and not yet confirmed, waiting for a choice and opted out."""
    rows = frappe.db.sql(f"""SELECT JSON_UNQUOTE(JSON_EXTRACT(arguments, '$.poll.state')) AS state,
        JSON_EXTRACT(arguments, '$.poll.option') AS choice, COUNT(*) AS count FROM `tab{RECIPIENT}`
        WHERE campaign=%s AND arguments LIKE '%%"poll"%%' GROUP BY state, choice""", name, as_dict=True)
    poll = snapshot['poll']
    options = [{'label': label, 'confirmed': 0, 'pending': 0} for label in poll.get('options') or []]
    counts = {ASKED: 0, OPTED_OUT: 0}
    for row in rows:
        choice = cint(row.choice) if row.choice not in (None, 'null') else None
        if row.state in (CONFIRMED, CHOSEN) and choice is not None and choice < len(options):
            options[choice]['confirmed' if row.state == CONFIRMED else 'pending'] += row.count
        elif row.state in counts:
            counts[row.state] += row.count
    return {**poll, 'buttons': template_buttons(snapshot), 'results': options, 'waiting': counts[ASKED],
            'opted_out': counts[OPTED_OUT]}


def as_object(value) -> dict:
    try:
        value = polls.as_object(value)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def claim(message) -> _dict | None:
    """The poll step an incoming WhatsApp tap answers: its recipient row, campaign poll and step; else None."""
    if message.get('legacy_source') or message.direction != 'Incoming' or message.message_type not in ('', None, 'text'):
        return None
    data, context = as_object(message.message_data), as_object(message.provider_context)
    selection = data.get('selection_id')
    if context.get('group_id') or not isinstance(selection, str) or not selection:
        return None
    if data.get('selection_type') == 'template_button':
        quoted = context.get('reply_to_message_id')
        name = quoted and frappe.db.get_value(RECIPIENT, {'destination': message.sender_endpoint, 'provider_id': quoted}, 'name')
        step = 'tap'
    else:
        found = CHOICE.fullmatch(selection)
        name, step = found.groups() if found else (None, None)
    row = name and frappe.db.get_value(RECIPIENT, name, ['name', 'campaign', 'destination'], as_dict=True)
    if not row or row.destination != message.sender_endpoint:
        return None
    campaign = frappe.db.get_value('Relay Campaign', row.campaign, ['channel', 'arguments', 'execution_user'], as_dict=True)
    poll = json.loads(campaign.arguments or '{}').get('poll') if campaign and campaign.channel == message.channel else None
    if not poll or not poll.get('question') or poll.get('closed'):
        return None
    if step == 'tap':
        button = data.get('text')
        step = 'in' if button == poll['opt_in'] else 'out' if poll.get('opt_out') and button == poll['opt_out'] else None
        if not step:
            return None
    return _dict(recipient=row.name, campaign=row.campaign, poll=poll, step=step, user=campaign.execution_user)


def claims(message) -> bool:
    return claim(message) is not None


def question(recipient: str, poll: dict) -> tuple[str, dict]:
    choices, _ = polls.prepare({'question': poll['question'], 'options': poll['options']})
    for number, row in enumerate(choices['choices']):
        row['value'] = f'cpoll:{recipient}:{number}'
    return 'choices', choices


def confirmation(recipient: str, poll: dict, option: int) -> tuple[str, dict]:
    return 'choices', {'body': f"You chose: {poll['options'][option]}\nConfirm your answer?", 'choices': [
        {'label': 'Confirm', 'value': f'cpoll:{recipient}:confirm:{option}'},
        {'label': 'Change', 'value': f'cpoll:{recipient}:change'}]}


def advance(state: dict, step: str, recipient: str, poll: dict) -> tuple[dict, tuple[str, dict] | None]:
    """The recipient's next poll state and the reply to send, if any. A confirmed answer is final."""
    current = state.get('state')
    if step == 'out':
        return (state if current == CONFIRMED else {**state, 'state': OPTED_OUT}), None
    if current == CONFIRMED:
        return state, ('text', {'text': ALREADY})
    if current == OPTED_OUT:
        return state, None
    if step in ('in', 'change'):
        return {**state, 'state': ASKED, 'option': None}, question(recipient, poll)
    option = int(step.removeprefix('confirm:'))
    if step.startswith('confirm:'):
        # Only the confirm of the current choice counts; one from before a change is stale.
        if current != CHOSEN or state.get('option') != option:
            return state, None
        return {**state, 'state': CONFIRMED}, ('text', {'text': poll['thanks']})
    if option >= len(poll['options']):
        return state, None
    return {**state, 'state': CHOSEN, 'option': option}, confirmation(recipient, poll, option)


def on_message(doc, method=None):
    """Record a poll tap on its recipient row and queue the reply; runs in the inbound message transaction."""
    step = claim(doc)
    if not step:
        return
    arguments = json.loads(frappe.db.get_value(RECIPIENT, step.recipient, 'arguments', for_update=True) or '{}')
    state, reply = advance(arguments.get('poll') or {}, step.step, step.recipient, step.poll)
    if step.step == 'out':
        from relay_core.opt_out import set_choice
        set_choice(doc.channel, doc.sender_endpoint, True)
    if state != arguments.get('poll'):
        arguments['poll'] = {**state, 'message': doc.name, 'at': str(doc.sent_at or doc.creation)}
        frappe.db.set_value(RECIPIENT, step.recipient, 'arguments', canonical(arguments), update_modified=False)
        from relay_core.bulk_updates import changed
        changed(step.campaign)
    if reply:
        frappe.enqueue('relay_core.campaign_polls.send_reply', message=doc.name, kind=reply[0], data=reply[1],
                       user=step.user, queue='short', enqueue_after_commit=True)


def send_reply(message, kind, data, user):
    """Send one poll step as the user who started the campaign; the message's request key makes a retry safe."""
    from relay_core.messaging import outgoing_poll, send_one
    previous = frappe.session.user
    token = outgoing_poll.set(message)
    try:
        frappe.set_user(user or 'Administrator')
        return send_one(message, kind, data, 'campaign-poll-' + message, quote=1)
    finally:
        outgoing_poll.reset(token)
        frappe.set_user(previous)

