"""Drive one test site in-process: signed Hub callbacks in, queued work drained against an in-process Hub, actions read back."""
import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from relay_core.ai.sim import personas

JOB_OPTIONS = ('queue', 'timeout', 'enqueue_after_commit', 'job_id', 'deduplicate', 'at_front', 'now', 'is_async',
               'job_name', 'on_success', 'on_failure')


def whatsapp_payload(phone: str, text: str, identifier: str) -> dict:
    message = {'from': phone, 'id': identifier, 'timestamp': str(int(time.time())), 'type': 'text', 'text': {'body': text}}
    value = {'messaging_product': 'whatsapp', 'metadata': {'phone_number_id': 'relay-sim'}, 'messages': [message]}
    return {'object': 'whatsapp_business_account', 'entry': [{'id': 'relay-sim', 'changes': [{'field': 'messages', 'value': value}]}]}


def signed(raw: bytes, secret: str, timestamp: str) -> dict:
    """The headers the Hub sends: HMAC-SHA256 over `timestamp.body`."""
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return {'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature}


def disclosure_texts() -> set[str]:
    from relay_core.ai.disclosure import DISCLOSURE
    from relay_core.ai.language import NOTICES
    return {DISCLOSURE, *NOTICES['disclosure'].values()}


class Driver:
    def __init__(self):
        from relay_core.settings import value
        self.account, self.secret = value('relay_hub_account'), value('relay_callback_secret')
        self.cursor = frappe.db.get_value('Relay Message Action', {}, 'name', order_by='name desc') or ''
        self.jobs, self.errors, self.events, self.hub_calls = [], [], [], []

    def hub(self, name: str, arguments: dict) -> dict:
        """The in-process Hub: every tool call is accepted with a new provider message id."""
        self.hub_calls.append((name, arguments))
        return {'success': True, 'messages': [{'id': 'wamid.sim.out.' + uuid.uuid4().hex[:20]}]}

    def post_inbound(self, scenario: dict, turn: dict) -> str:
        """Post the turn's text from the persona's phone; returns the provider message id."""
        person = personas.get(scenario['persona'])
        identifier = 'wamid.sim.' + uuid.uuid4().hex[:20]
        self.deliver(time.time_ns(), whatsapp_payload(person.phone, turn['in'], identifier))
        return identifier

    def deliver(self, event_id: int, payload: dict) -> None:
        from relay_core import inbound
        raw = json.dumps({'account': self.account, 'events': [{'id': event_id, 'payload': payload}]}).encode()
        request = SimpleNamespace(get_data=lambda: raw, headers=signed(raw, self.secret, str(int(time.time()))))
        frappe.db.commit()  # Each callback is its own HTTP transaction.
        with patch.object(frappe, 'request', request, create=True), patch.object(frappe, 'publish_realtime'):
            inbound.receive()
        frappe.db.commit()
        self.events.append((event_id, payload))

    def repeat_last(self) -> None:
        """The Hub retries a callback it did not see acknowledged: same event id, same payload."""
        self.deliver(*self.events[-1])

    def collect(self, method, **kwargs) -> None:
        self.jobs.append((method, {key: value for key, value in kwargs.items() if key not in JOB_OPTIONS}))

    def drain(self, rounds: int = 50) -> int:
        """Project Hub events, run the message hooks and every job they queue, until nothing is left."""
        from relay_core.automation import projection, queue
        from relay_core.hub import HubClient
        done = 0
        hub = lambda client, name, arguments: self.hub(name, arguments)
        with patch.object(frappe, 'enqueue', side_effect=self.collect), patch.object(queue.Drain, 'wake', lambda self: None), \
                patch.object(frappe, 'publish_realtime'), patch.object(HubClient, 'call_tool', hub):
            for _ in range(rounds):
                events = frappe.get_all('Relay Hub Event', filters={'projection_status': 'Pending'}, pluck='name',
                                        order_by='name asc')
                if events:
                    projection.project_names(events)
                progress = len(events) + (queue.drain() or 0) + self.run_jobs()
                done += progress
                if not progress:
                    break
        return done

    def run_jobs(self) -> int:
        count = 0
        while self.jobs:
            method, kwargs = self.jobs.pop(0)
            try:
                frappe.get_attr(method)(**kwargs)
                frappe.db.commit()
            except Exception as error:
                frappe.db.rollback()
                self.errors.append({'method': method, 'error': f'{type(error).__name__}: {error}'[:300]})
            count += 1
        return count

    def outbound(self) -> list[dict]:
        """Relay Message Action rows since the last read, with their text and a `disclosure` slot marker."""
        rows = frappe.get_all('Relay Message Action', filters={'name': ['>', self.cursor]},
                              fields=['name', 'payload', 'status', 'source_message'], order_by='name asc')
        if rows:
            self.cursor = rows[-1].name
        notices = disclosure_texts()
        result = []
        for row in rows:
            content = (json.loads(row.payload or '{}').get('content') or {})
            text = content.get('text') if isinstance(content, dict) else None
            result.append({'name': row.name, 'status': row.status, 'source_message': row.source_message, 'text': text,
                           'slot': 'disclosure' if text in notices else None})
        return result
