import json
import threading
import time
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import frappe
import relay_core.mcp_tools  # noqa: F401  Registers every tool.
from relay_core.mcp_tools import chats, coordination, registry

CON, KEY = 'RELAY-CON-0000000001', 'agent-key-0001'


class Row(dict):
    __getattr__ = dict.get


class FakeSite:
    """Stands in for the frappe module: the surface coordination uses: Redis hash and locks, messages, actions and Activity Log rows."""

    def __init__(self):
        self.local = threading.local()
        self.hash, self.locks, self.logs = {}, {}, []
        self.values = {'relay-mcp-client:agent-a@x.test': 'agent-a'}
        self.sent = {}
        self.messages = [Row(name='RELAY-MSG-0000000001', relay_contact=CON, direction='Incoming', content='Hi',
                             creation=datetime(2026, 10, 30, 10))]
        self.actions = []
        self.contact = {'automation_paused': 0, 'automation_generation': 4}
        self.cache = types.SimpleNamespace(hgetall=lambda name: dict(self.hash), hset=self.hset,
                                           hdel=lambda name, key: self.hash.pop(key, None), lock=self.lock, make_key=lambda key: key,
                                           get_value=self.values.get, set_value=self.set_value)
        self.db = types.SimpleNamespace(commit=Mock(), get_value=self.get_value)
        self.log_error = Mock()
        self.PermissionError, self.DoesNotExistError = frappe.PermissionError, frappe.DoesNotExistError
        self.utils = types.SimpleNamespace(now_datetime=datetime.now)

    def set_value(self, key, value, expires_in_sec=None):
        self.values[key] = value

    def hset(self, name, key, value):
        self.hash[key] = value

    def lock(self, key, **kwargs):
        return self.locks.setdefault(key, threading.Lock())

    @property
    def session(self):
        return types.SimpleNamespace(user=self.local.user)

    def set_user(self, user):
        self.local.user = user

    def get_value(self, doctype, filters, fields=None, as_dict=False):
        if doctype == 'Relay Contact':
            return self.contact[fields]
        row = next(item for item in self.messages if item.name == filters)
        return Row(relay_contact=row.relay_contact, creation=row.creation) if as_dict else row.relay_contact

    def get_list(self, doctype, filters=None, fields=None, order_by='', limit_page_length=0, pluck=None):
        rows = [row for row in self.messages if row.name > (filters or {}).get('name', ['>', ''])[1]]
        if filters and filters.get('direction'):
            rows = [row for row in rows if row.direction == filters['direction']]
        rows = sorted(rows, key=lambda row: row.name, reverse='desc' in order_by)[:limit_page_length or None]
        return [row[pluck] for row in rows] if pluck else rows

    def get_all(self, doctype, filters=None, fields=None, **kwargs):
        if doctype == 'Relay Message Action':
            return [row for row in self.actions if row.outbound_message in filters['outbound_message'][1]]
        names = filters.get('link_name', ['in', None])[1]
        return [Row(link_name=log['link_name'], content=log['content']) for log in self.logs if names is None or log['link_name'] in names]

    def get_doc(self, values):
        return types.SimpleNamespace(insert=lambda ignore_permissions: self.logs.append(values))

    def send(self, text, key=None):
        """What Core's send does: a new outgoing message and its action, owned by the session user; a known key repeats."""
        if key in self.sent:
            return self.sent[key]
        name = f'RELAY-MSG-{len(self.messages) + 1:010d}'
        time.sleep(0.05)  # A Hub call; the other agent waits on the chat lock meanwhile.
        self.messages.append(Row(name=name, relay_contact=CON, direction='Outgoing', content=text, creation=datetime.now()))
        action = f'RELAY-MA-{len(self.actions) + 1:010d}'
        self.actions.append(Row(name=action, outbound_message=name, owner=self.local.user))
        self.sent[key] = {'action': action, 'status': 'Submitted', 'message': name}
        return self.sent[key]


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite()
        self.site.set_user('agent-a@x.test')
        fake = self.site
        self.takeover = Mock(side_effect=self.pause)
        self.send = Mock(side_effect=lambda message, kind, data, request_key, **kwargs: self.site.send(data['text'], request_key))
        self.patches = [patch.object(coordination, 'frappe', fake), patch.object(chats, 'frappe', fake),
                        patch('relay_core.permissions.readable_contact'), patch('relay_core.automation.service.takeover', self.takeover),
                        patch('relay_core.messaging.actions', return_value={'items': []}), patch('relay_core.messaging.send', self.send)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def pause(self, contact, paused):
        self.site.contact.update(automation_paused=paused, automation_generation=self.site.contact['automation_generation'] + 1)
        return {'paused': paused, 'generation': self.site.contact['automation_generation']}

    def reply(self, user, text, after='RELAY-MSG-0000000001', results=None):
        self.site.set_user(user)
        result = registry.call('chat_send_text', {'message': 'RELAY-MSG-0000000001', 'text': text, 'request_key': KEY + user[:7],
                                                  'after_message': after})
        if results is not None:
            results[user] = result
        return result

    def test_two_agents_racing_on_one_chat_send_one_reply(self):
        results = {}
        threads = [threading.Thread(target=self.reply, args=(user, 'Reply from ' + user, 'RELAY-MSG-0000000001', results))
                   for user in ('agent-a@x.test', 'agent-b@x.test')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.send.call_count, 1)
        errors = [result for result in results.values() if result['isError']]
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0]['content'][0]['text'].startswith('Chat changed: Outgoing RELAY-MSG-0000000002'))
        winner = next(result for result in results.values() if not result['isError'])['structuredContent']
        self.assertEqual(winner['via'], 'mcp')

    def test_repeating_your_own_request_key_returns_the_first_send(self):
        first = self.reply('agent-a@x.test', 'Once')
        again = self.reply('agent-a@x.test', 'Once')
        self.assertFalse(again['isError'], again)
        self.assertEqual(self.send.call_count, 2)  # Core gets the repeat and answers it from the first action.
        self.assertEqual(again['structuredContent']['message'], first['structuredContent']['message'])
        self.assertEqual(len(self.site.messages), 2)
        self.assertTrue(self.reply('agent-b@x.test', 'Other')['isError'])

    def test_claim_blocks_other_agents_and_pauses_then_resumes_automation(self):
        claim = registry.call('chat_claim', {'contact': CON, 'minutes': 10})['structuredContent']
        self.assertEqual((claim['claimed_by'], claim['ai_paused']), ('agent-a@x.test (agent-a)', True))
        self.takeover.assert_called_once_with(CON, 1)
        self.assertEqual(self.site.contact['automation_paused'], 1)

        refused = self.reply('agent-b@x.test', 'Me too')
        self.assertTrue(refused['isError'])
        self.assertIn('Chat claimed by agent-a@x.test (agent-a) until', refused['content'][0]['text'])
        self.assertIn('Chat claimed by', registry.call('chat_claim', {'contact': CON, 'minutes': 5})['content'][0]['text'])
        self.send.assert_not_called()

        self.assertFalse(self.reply('agent-a@x.test', 'Holder answers')['isError'])
        self.assertIn('Only agent-a@x.test', (self.site.set_user('agent-b@x.test') or
                                              registry.call('chat_release', {'contact': CON}))['content'][0]['text'])
        self.site.set_user('agent-a@x.test')
        self.assertTrue(registry.call('chat_release', {'contact': CON})['structuredContent']['released'])
        self.takeover.assert_called_with(CON, 0)
        self.assertEqual(self.site.contact['automation_paused'], 0)

    def test_expired_claim_resumes_automation_but_not_a_later_staff_pause(self):
        registry.call('chat_claim', {'contact': CON, 'minutes': 1})
        stored = json.loads(self.site.hash[CON])
        self.site.hash[CON] = json.dumps(dict(stored, until=time.time() - 1))
        self.assertEqual(coordination.claims(), {})
        self.assertEqual(self.site.contact['automation_paused'], 0)

        registry.call('chat_claim', {'contact': CON, 'minutes': 1})
        self.pause(CON, 1)  # Staff paused automation again by hand during the claim.
        self.site.hash[CON] = json.dumps(dict(json.loads(self.site.hash[CON]), until=time.time() - 1))
        coordination.claims()
        self.assertEqual(self.site.contact['automation_paused'], 1)

    def test_an_already_paused_chat_stays_paused_after_release(self):
        self.site.contact['automation_paused'] = 1
        registry.call('chat_claim', {'contact': CON, 'minutes': 3})
        registry.call('chat_release', {'contact': CON})
        self.takeover.assert_not_called()

    def test_cursor_returns_replies_of_other_actors(self):
        cursor = registry.call('changes_since', {})['structuredContent']['cursor']
        self.assertEqual(cursor, 'RELAY-MSG-0000000001')
        self.reply('agent-a@x.test', 'From agent A')
        self.site.set_user('staff@x.test')
        self.site.send('From staff')
        self.site.messages.append(Row(name='RELAY-MSG-0000000004', relay_contact=CON, direction='Incoming', content='Thanks'))
        self.site.set_user('agent-b@x.test')
        page = registry.call('changes_since', {'cursor': cursor})['structuredContent']
        actors = [(event['type'], event.get('sent_by'), event.get('via')) for event in page['events']]
        self.assertEqual(actors, [('reply', 'agent-a@x.test', 'mcp'), ('reply', 'staff@x.test', 'staff'), ('inbound', None, None)])
        self.assertEqual(page['cursor'], 'RELAY-MSG-0000000004')

    def test_sends_are_audited_with_actor_client_and_response_time(self):
        self.reply('agent-a@x.test', 'Logged')
        log = self.site.logs[0]
        details = json.loads(log['content'])
        self.assertEqual((log['subject'], log['user'], log['reference_name'], log['link_name']),
                         ('MCP chat_send_text', 'agent-a@x.test', CON, 'RELAY-MA-0000000001'))
        self.assertEqual((details['client'], details['message']), ('agent-a', 'RELAY-MSG-0000000002'))
        self.assertGreater(details['response_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
