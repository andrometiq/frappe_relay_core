"""Keep contact details out of model prompts and drop old AI call payloads."""
import re

import frappe
from frappe.utils import add_days, cint, now_datetime

from relay_core.ai.reply_guard import EMAIL, phone_matches

PLACEHOLDER = re.compile(r'\[(?:PHONE|EMAIL|PERSON)_\d+\]')
DEFAULT_RETENTION_DAYS = 30


class Minimiser:
    """Replace emails, phones and the sender's full name with `[EMAIL_n]`, `[PHONE_n]` and `[PERSON_n]` in model
    input, and put the values back in model output. Without a `scope` only emails and phones are masked."""

    def __init__(self, scope: dict | None = None):
        self.table: dict[str, str] = {}
        self.known: dict[tuple[str, str], str] = {}
        name = frappe.db.get_value('Contact', scope['person'], 'full_name') if scope and scope.get('person') else ''
        name = ' '.join(str(name or '').split())
        self.name = re.compile(r'(?<!\w)' + re.escape(name).replace(r'\ ', r'\s+') + r'(?!\w)',
                               re.IGNORECASE) if name else None

    def mask(self, value):
        if isinstance(value, dict):
            return {key: self.mask(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.mask(item) for item in value]
        if not isinstance(value, str):
            return value
        value = EMAIL.sub(lambda found: self.placeholder('EMAIL', found[0]), value)
        parts, end = [], 0
        for found in phone_matches(value):
            parts += [value[end:found.start()], self.placeholder('PHONE', value[found.start():found.end()])]
            end = found.end()
        value = ''.join(parts) + value[end:]
        return self.name.sub(lambda found: self.placeholder('PERSON', found[0]), value) if self.name else value

    def unmask(self, value):
        if isinstance(value, dict):
            return {key: self.unmask(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.unmask(item) for item in value]
        if not isinstance(value, str):
            return value
        return PLACEHOLDER.sub(lambda found: self.table.get(found[0], found[0]), value)

    def placeholder(self, kind: str, value: str) -> str:
        key = (kind, re.sub(r'\D', '', value) if kind == 'PHONE' else ' '.join(value.casefold().split()))
        if key not in self.known:
            count = sum(known == kind for known, _ in self.known) + 1
            self.known[key] = f'[{kind}_{count}]'
            self.table[self.known[key]] = value
        return self.known[key]


def purge_ai_payloads() -> None:
    """Blank the request and response text of automation run AI call logs older than the retention days."""
    days = cint(frappe.db.get_single_value('Relay Settings', 'ai_log_retention_days')) or DEFAULT_RETENTION_DAYS
    frappe.db.set_value('Document AI Call Log', {'reference_doctype': 'Relay Automation Run',
        'creation': ['<', add_days(now_datetime(), -days)], 'request_payload': ['is', 'set']},
        {'request_payload': '', 'response_payload': '', 'raw_response': ''}, update_modified=False)
