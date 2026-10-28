"""Flow step latency with 1,000 open runs on a site without a Hub; sends are captured, none leaves.

Usage (from the bench sites folder):
  RELAY_FLOW_TEST_SITE=relay-flows-test.localhost RELAY_FLOW_PERF_RUNS=1000 \\
  ../env/bin/python -W ignore ../apps/relay_core/tests/perf_flow_site.py
"""
import os
import statistics
import time
from unittest.mock import patch

import integration_flow_builder_site as site
from integration_flow_builder_site import Conversation, RUN, fixtures, flows, frappe, person, queue

RUNS = int(os.environ.get('RELAY_FLOW_PERF_RUNS', '1000'))
NODES = [
    {'id': 'ask_name', 'kind': 'input', 'text': 'Your name?', 'variable': 'name', 'input_type': 'text'},
    {'id': 'thanks', 'kind': 'reply', 'text': 'Thanks {{name}}.'},
    {'id': 'ask_rating', 'kind': 'input', 'text': 'Rate us', 'variable': 'rating', 'input_type': 'choice',
     'choices': [{'label': 'Good', 'value': 'good'}, {'label': 'Bad', 'value': 'bad'}]},
    {'id': 'done', 'kind': 'end', 'text': 'Bye {{name}}.'},
]


def milliseconds(samples):
    ordered = sorted(samples)
    pick = lambda share: ordered[min(len(ordered) - 1, int(len(ordered) * share))] * 1000
    return f'p50 {statistics.median(ordered) * 1000:.1f} ms, p95 {pick(0.95):.1f} ms, max {ordered[-1] * 1000:.1f} ms (n={len(ordered)})'


def step(chat, text):
    """One inbound reply through admission; returns the flow job time alone."""
    message = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': chat.contact, 'channel': chat.channel.name,
        'direction': 'Incoming', 'content': text, 'message_type': 'text', 'status': 'Sent', 'sender_endpoint': chat.number,
        'provider_context': '{"provider": "WhatsApp", "message_id": "wamid.%d"}' % time.time_ns(),
        'message_data': frappe.as_json({'kind': 'text', 'text': text})}).insert(ignore_permissions=True)
    frappe.db.commit()
    queue.drain()
    started = time.perf_counter()
    while site.JOBS:
        flows.process(site.JOBS.pop(0))
    return message, time.perf_counter() - started


def main():
    runner, note, channel = fixtures()
    frappe.db.set_single_value('Relay Settings', 'enable_flows', 1)
    flow = flows.save({'title': 'Perf ' + RUN, 'command': '/perf' + str(time.time_ns())[-6:], 'channel': channel.name,
                       'execution_user': runner, 'business_doctype': 'Note', 'nodes': NODES})
    command = flow['command']
    flows.publish(flow['name']); flows.set_enabled(flow['name'], 1)
    frappe.db.commit()
    with patch.object(frappe, 'enqueue', side_effect=site.capture), patch.object(flows, 'send', side_effect=site.fake_send), \
         patch.object(queue.AUTOMATION, 'wake', return_value=None), \
         patch.object(site.messaging, 'connection_value', return_value=channel.account):
        started = time.perf_counter()
        chats = [Conversation(channel, *person(note, channel, f'P{index} {RUN}')) for index in range(RUNS)]
        frappe.db.commit()
        print(f'setup: {RUNS} contacts in {time.perf_counter() - started:.1f} s')

        starts = [step(chat, command)[1] for chat in chats]
        waiting = frappe.db.count('Relay Flow Run', {'flow': flow['name'], 'status': 'Waiting'})
        assert waiting == RUNS, waiting
        print(f'start step (trigger, prompt) with up to {RUNS} open runs: {milliseconds(starts)}')

        replies = []
        for index, chat in enumerate(chats):
            replies.append(step(chat, 'Name ' + str(index))[1])
        print(f'reply step (parse, reply, next prompt) with {RUNS} open runs: {milliseconds(replies)}')

        key = frappe.db.get_value('Relay Flow Run', {'flow': flow['name'], 'status': 'Waiting'}, 'conversation_key')
        lookups = []
        for _ in range(200):
            begin = time.perf_counter(); flows.active(key); lookups.append(time.perf_counter() - begin)
        plan = frappe.db.sql("EXPLAIN SELECT name FROM `tabRelay Flow Run` WHERE conversation_key=%s AND status IN ('Running','Waiting')", key, as_dict=True)
        print(f'open run lookup per conversation: {milliseconds(lookups)}; index used: {plan[0].get("key")}')
        assert plan[0].get('key'), plan

        finals = [step(chat, '1')[1] for chat in chats]
        print(f'final step (choice, end message): {milliseconds(finals)}')
        done = frappe.db.count('Relay Flow Run', {'flow': flow['name'], 'status': 'Completed'})
        assert done == RUNS, done
        assert all(text == f'Bye Name {index}.' for index, chat in enumerate(chats) for text in site.texts(chat.contact)[-1:])
    flows.set_enabled(flow['name'], 0)
    frappe.db.commit()
    print('ALL PASS', RUN)


if __name__ == '__main__':
    main()
