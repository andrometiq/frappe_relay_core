"""A voice note Relay cannot transcribe gets one gentle request to type it, not a staff handoff."""
import json

import frappe

VOICE_NOTICE = "Sorry, I can't listen to voice notes right now. Could you please type your message? 🙏"
HISTORY = 5


def is_untranscribed(message) -> bool:
    """A voice note with no transcript and none on the way."""
    return (message.get('message_type') in ('voice', 'audio') and not (message.get('transcript') or '').strip()
            and message.get('transcript_status') != 'Pending')


def notices() -> set[str]:
    from relay_core.ai.language import NOTICES
    return {VOICE_NOTICE, *NOTICES['voice'].values()}


def notice_text(language: str | None) -> str:
    from relay_core.ai.language import NOTICES
    return NOTICES['voice'].get(language, VOICE_NOTICE)


def language(message) -> str | None:
    """The latest clear language the sender wrote in this conversation; the audio itself gives no evidence."""
    from relay_core.ai.language import resolve
    rows = frappe.get_all('Relay Message', filters={'conversation_key': message.conversation_key,
        'direction': 'Incoming', 'name': ['!=', message.name]}, fields=['content', 'transcript'],
        order_by='creation desc', limit_page_length=HISTORY)
    history = [{'direction': 'Incoming', 'content': row.transcript or row.content} for row in reversed(rows)]
    hint = resolve('', history)
    return hint['language'] if hint['script'] else None


def already_sent(run) -> bool:
    """One notice per conversation episode, so repeated voice notes are not answered again."""
    return bool(run.get('ticket') and frappe.get_all('Relay Automation Run', filters={'ticket': run.ticket,
        'name': ['!=', run.name], 'decision': ['like', '%"notice": "voice"%']}, pluck='name', limit_page_length=1))


def decision(run, message, user: str, scope: dict) -> dict | None:
    """The fixed notice as a no-ticket decline, or None when this episode already has one."""
    from relay_core.ai.tools import fingerprint
    if already_sent(run):
        return None
    spoken = language(message)
    return dict(reply=notice_text(spoken), handoff=False, reason='', decline=True, notice='voice',
                language=spoken, reads=[], user=user, scope=fingerprint(scope))


def admit(run, message, skills) -> bool:
    """Bind the default skill without matching, which needs text; False leaves other messages to matching."""
    from relay_core.ai.skills import is_default
    from relay_core.ai.service import select_skill
    skill = next((skill for skill in skills if is_default(skill)), skills[0] if skills else None)
    if not skill or not is_untranscribed(message):
        return False
    select_skill(run, message, skill.name)
    run.match_result = json.dumps(dict(selected=skill.name, scores=[], method='voice',
                                       reason='Voice note without transcript'))
    return True
