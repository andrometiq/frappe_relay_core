"""Real database checks for topic ownership, conflict detection and human overrides."""
from unittest.mock import patch
import os
import json
import time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sites = root / '.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve() == sites.resolve()
os.chdir(sites)
import frappe
from relay_core import topics, teams
frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name == 'relay_ai_test_20260922' and frappe.conf.db_port == 18433
frappe.connect()
frappe.set_user('Administrator')
contacts = frappe.get_all('Relay Contact', filters={'display_name': ['like', 'Inbox %']}, pluck='name', limit_page_length=2)
assert len(contacts) == 2
contact, other = contacts
message = frappe.db.get_value('Relay Message', {'relay_contact': contact}, 'name')
wrong = frappe.db.get_value('Relay Message', {'relay_contact': other}, 'name')
created = []
def rejected(fn):
    try:
        fn()
    except (frappe.ValidationError, frappe.PermissionError):
        frappe.db.rollback()
    else:
        raise AssertionError('Expected rejection')
try:
    key = 'fixture-' + str(time.time_ns())
    frappe.db.savepoint('topic_membership_scale')
    stamp=frappe.utils.now_datetime()
    rows=[['query-'+key+'-'+str(i),contact,'Query fixture',json.dumps(['unrelated-'+str(i)]),stamp,stamp] for i in range(1000)]
    rows[-1][3]=json.dumps(['quoted"message','MSG-1234'])
    frappe.db.bulk_insert('Relay Conversation Topic',fields=['name','relay_contact','title','messages','creation','modified'],values=rows)
    assert topics.membership_conflict(contact,['quoted"message'])
    assert not topics.membership_conflict(contact,['quoted"message'],exclude=rows[-1][0])
    assert not topics.membership_conflict(other,['quoted"message'])
    assert not topics.membership_conflict(contact,['MSG-123'])
    assert not topics.membership_conflict(contact,['missing-'+str(i) for i in range(500)])
    assert not topics.membership_conflict(contact,[])
    frappe.db.rollback(save_point='topic_membership_scale')
    print('PASS exact JSON membership with 1000 topics, 500 candidates, escaped identifiers and contact/self exclusion')
    manual_values = {'title': 'Retry-safe empty topic', 'messages': []}
    with patch('relay_core.realtime.contact_changed') as changed_event:
        manual = topics.save(contact, manual_values, request_key=key)
        changed_event.assert_called_once_with(contact,'topics')
    created.append(manual['name'])
    assert topics.save(contact, manual_values, request_key=key)['name'] == manual['name']
    rejected(lambda: topics.save(contact, {'title': 'Changed retry'}, request_key=key))
    changed = topics.save(contact, {'title': 'Later human edit', 'modified': str(manual['modified'])}, name=manual['name'])
    recovered = topics.save(contact, manual_values, request_key=key)
    assert recovered['name'] == manual['name'] and recovered['title'] == changed['title']
    first = topics.upsert(contact, {'title': 'Payment question', 'messages': [message]}, source_key=key)
    created.append(first['name'])
    replay = topics.upsert(contact, {'title': 'Updated automatic summary', 'messages': [message]}, source_key=key)
    assert replay['name'] == first['name'] and replay['message_count'] == 1
    rejected(lambda: topics.save(contact, {'title': 'Duplicate assignment', 'messages': [message]}))
    rejected(lambda: topics.save(contact, {'title': 'Wrong conversation', 'messages': [wrong]}))
    rejected(lambda: topics.save(other, {'title': 'Wrong topic', 'modified': replay['modified']}, name=first['name']))
    edited = topics.save(contact, {'title': 'Human title', 'status': 'Resolved', 'messages': [message], 'modified': str(replay['modified'])}, name=first['name'])
    assert edited['human_edited'] and edited['status'] == 'Resolved'
    rejected(lambda: topics.save(contact, {'title': 'Stale edit', 'modified': str(replay['modified'])}, name=first['name']))
    preserved = topics.upsert(contact, {'title': 'Automatic overwrite', 'messages': [message]}, source_key=key)
    assert preserved['preserved'] and preserved['title'] == 'Human title'
    assert first['name'] in [row['name'] for row in topics.directory(contact)['items']]
    team = teams.save('Topic test ' + key, ['relay-agent-a@example.invalid', 'relay-agent-b@example.invalid'])
    teams.assign(contact, team['name'], 'relay-agent-a@example.invalid')
    frappe.db.commit()
    frappe.set_user('relay-agent-a@example.invalid')
    assert first['name'] in [row['name'] for row in topics.directory(contact)['items']]
    edited = topics.save(contact, {'title': 'Operator edit', 'messages': [message], 'modified': str(edited['modified'])}, name=first['name'])
    assert edited['title'] == 'Operator edit'
    frappe.set_user('relay-agent-b@example.invalid')
    rejected(lambda: topics.directory(contact))
    rejected(lambda: topics.save(contact, {'title': 'Unassigned edit', 'modified': str(edited['modified'])}, name=first['name']))
    frappe.set_user('Guest')
    rejected(lambda: topics.directory(contact))
    rejected(lambda: topics.save(contact, {'title': 'Forbidden'}))
    print('PASS topic replay, unique membership, cross-contact isolation, stale edit rejection, human preservation, assigned operator edits, unassigned and guest denial')
finally:
    frappe.set_user('Administrator')
    for name in created:
        frappe.delete_doc('Relay Conversation Topic', name, ignore_permissions=True)
    frappe.db.commit()
    frappe.destroy()
