"""Authenticated-event enrollment with no external messaging."""
import json,os,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import enrollment,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
run=str(time.time_ns());account='enrollment-'+run
contacts=frappe.get_all('Relay Contact',filters={'display_name':['like','Inbox %']},pluck='name',limit_page_length=2);assert len(contacts)==2
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='Telegram',account=account,enabled=1)).insert()
payload={'channel':'Telegram','direction':'inbound','provider_id':'17','sender':'9123456','body':'Unlinked fixture','payload':{'update_id':17,'message':{'message_id':19,'date':1700000000,'chat':{'id':9123456,'type':'private'},'from':{'id':9123456,'is_bot':False},'text':'Unlinked fixture'}}}
with patch.object(frappe,'enqueue'):
 event=frappe.get_doc(dict(doctype='Relay Hub Event',event_key='enrollment-'+run,account=account,hub_event_id=run,payload=json.dumps(payload),projection_status='Uncategorized')).insert()
frappe.db.commit()
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Unauthorized enrollment succeeded')
try:
 with patch.object(enrollment,'connection_value',return_value=account),patch.object(whatsapp,'client',side_effect=AssertionError('No provider side effects')),patch.object(frappe,'enqueue'):
  pending=enrollment.pending()['items'];assert len(pending)==1 and pending[0]['endpoint']=='9123456'
  try:enrollment.bind(event.name,'spoofed-id',contacts[0])
  except frappe.ValidationError:pass
  else:raise AssertionError('Caller invented provider identity')
  result=enrollment.bind(event.name,'17',contacts[0]);assert result['status']=='Projected'
  assert enrollment.bind(event.name,'17',contacts[0])==result
  assert frappe.db.count('Relay Message',{'channel':channel.name})==1
  assert not enrollment.pending()['items']
  try:enrollment.bind(event.name,'17',contacts[1])
  except frappe.ValidationError:pass
  else:raise AssertionError('Existing sender reassigned')
  endpoint=frappe.db.get_value('Relay Contact Endpoint',{'channel':channel.name},'name')
  frappe.db.set_value('Relay Contact Endpoint',endpoint,'verified',0);frappe.db.commit()
  try:enrollment.bind(event.name,'17',contacts[0])
  except frappe.ValidationError:pass
  else:raise AssertionError('Revoked endpoint silently re-enabled')
  frappe.set_user('relay-agent-a@example.invalid');denied(enrollment.pending);denied(lambda:enrollment.bind(event.name,'17',contacts[0]))
  frappe.set_user('Administrator')
 with patch.object(enrollment,'connection_value',return_value='another-account'):
  denied(lambda:enrollment.bind(event.name,'17',contacts[0]))
 print('PASS curated pending senders, source-derived identity, projection/retry deduplication, reassignment and revocation denial, agent/account boundaries, no provider calls')
finally:frappe.destroy()
