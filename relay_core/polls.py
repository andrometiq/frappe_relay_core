"""WhatsApp polls. Cloud API has no native poll message, so a poll goes out as
reply buttons (up to 3 options) or a list (4-10 options), and each tap is the
sender's current vote on the poll message."""
import json

import frappe
from frappe.utils import get_datetime

from relay_core.message_types import text
from relay_core.message_updates import provider_key

OPTION_PREFIX = 'poll-'


def prepare(data: dict) -> tuple[dict, dict]:
    """Interactive choices to send and the poll content to store."""
    if set(data) - {'question', 'options'}:
        raise ValueError('A poll takes a question and options only')
    question = text(data.get('question'), 1024, required=True).strip()
    options = data.get('options')
    if not isinstance(options, list) or not 2 <= len(options) <= 10:
        raise ValueError('A WhatsApp poll needs 2-10 options')
    # Meta allows 20 characters on a reply button and 24 on a list row.
    limit = 20 if len(options) <= 3 else 24
    if any(not isinstance(option, str) or len(option.strip()) > limit for option in options):
        raise ValueError(f'Poll options can have up to {limit} characters with {len(options)} options')
    options = [text(option, limit, required=True).strip() for option in options]
    if len({option.casefold() for option in options}) != len(options):
        raise ValueError('Poll options must be different')
    choices = [{'label': option, 'value': OPTION_PREFIX + str(number)} for number, option in enumerate(options, 1)]
    return ({'body': question, 'choices': choices, 'button': 'Vote'},
            {'kind': 'poll', 'poll': {'question': question, 'options': options, 'votes': {}}})


def as_object(value) -> dict:
    return json.loads(value or '{}') if isinstance(value, str) else value or {}


def get_option(selection: str, options: list) -> int | None:
    number = selection.removeprefix(OPTION_PREFIX)
    if selection == number or not number.isdigit() or not 1 <= int(number) <= len(options):
        return None
    return int(number) - 1


def record_vote(message) -> str | None:
    """Count an interactive reply to our poll as its sender's vote; return the poll name.

    The reply must quote the poll and come from the same contact and chat. A later tap replaces
    the earlier vote; a tap that arrives late after a newer one is ignored.
    """
    data = as_object(message.message_data)
    context = as_object(message.provider_context)
    selection, target = data.get('selection_id') or '', context.get('reply_to_message_id')
    if not selection.startswith(OPTION_PREFIX) or not target or context.get('group_id'):
        return None
    name = frappe.db.get_value('Relay Message', {'provider_message_key': provider_key(message.channel, message.sender_endpoint, target)},
                               'name', for_update=True)
    if not name:
        return None
    poll = frappe.get_doc('Relay Message', name)
    if (poll.message_type != 'poll' or poll.direction != 'Outgoing' or poll.relay_contact != message.relay_contact
            or poll.sender_endpoint != message.sender_endpoint or poll.channel != message.channel):
        return None
    content = as_object(poll.message_data)
    option = get_option(selection, content['poll']['options'])
    if option is None:
        return None
    votes = content['poll'].setdefault('votes', {})
    at = str(get_datetime(message.sent_at))
    if message.relay_contact in votes and votes[message.relay_contact]['at'] > at:
        return None
    votes[message.relay_contact] = {'option': option, 'message': message.name, 'at': at}
    frappe.db.set_value('Relay Message', name, 'message_data', json.dumps(content, ensure_ascii=False))
    from relay_core.realtime import changed
    changed(poll)
    return name
