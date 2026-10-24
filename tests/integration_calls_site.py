"""Call history/signaling boundaries in the guarded synthetic Frappe site."""
from site_labels import run_label
import json
import os
from pathlib import Path
import time
from unittest.mock import patch, Mock
sites=os.environ.get('RELAY_AUTOMATION_TEST_SITES')
assert sites and Path(sites).resolve()==(Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites').resolve()
os.chdir(sites)
import frappe
from relay_core import call_records, teams, whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922'
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
run = run_label();users=['relay-agent-a@example.invalid','relay-agent-b@example.invalid']
# These users and business permissions are installed by the inbox suite.
for user in users:assert frappe.db.exists('User',user)
business_type='Relay Inbox Simulation Business';account='call-fixture-'+run
business=frappe.get_doc({'doctype':business_type,'title':'Calls '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'WhatsApp','account':account,'enabled':1}).insert()
people=[];contacts=[]
for index,user in enumerate(users):
 person=frappe.get_doc({'doctype':'Contact','first_name':'Call '+str(index)+' '+run,'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
 contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':person.first_name}).insert()
 frappe.get_doc({'doctype':'Relay Contact Endpoint','relay_contact':contact.name,'channel':channel.name,'endpoint':'91900000000'+str(index),'verified':1}).insert()
 teams.assign(contact.name,assigned_to=user);people.append(person);contacts.append(contact)
frappe.db.commit();stamp=int(time.time())
def event(index,kind='connect',timestamp=stamp):
 return {'id':'call-'+run+'-'+str(index),'from':'91900000000'+str(index),'event':kind,'timestamp':str(timestamp),'session':{'sdp_type':'offer','sdp':'v=0\r\nfixture-'+str(index)}}
def payload(calls):return {'entry':[{'changes':[{'value':{'calls':calls,'messages':[{'text':{'body':'unrelated private provider message'}}]}}]}]}
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Unauthorized call access succeeded')
try:
 for _ in range(2):call_records.ingest(payload([event(0),event(1)]),channel.name)
 frappe.db.commit();assert frappe.db.count('Relay Call',{'channel':channel.name})==2
 with patch.object(call_records,'connection_value',return_value=account):
  frappe.set_user(users[0]);history=call_records.history()['items'];own=next(row for row in history if row.provider_id==event(0)['id'])
  assert not any(row.provider_id==event(1)['id'] for row in history)
  assert call_records.authorize({'action':'accept','id':event(0)['id']})==(channel.name,contacts[0].name)
  denied(lambda:call_records.authorize({'action':'accept','id':event(1)['id']}))
  denied(lambda:whatsapp.prepare('events.latest'))
  denied(lambda:call_records.authorize({'action':'connect','to':'919000000001'},people[0].name))
  hub=Mock();hub.execute.return_value={'events':[{'id':'1','payload':payload([event(0),event(1)])}],'next':'1'}
  with patch.object(whatsapp,'checked_client',return_value=(hub,{})):
   result=call_records.events();raw=json.dumps(result);assert event(0)['id'] in raw and event(1)['id'] not in raw and 'unrelated private' not in raw
  frappe.set_user('Administrator');call_records.ingest(payload([event(0,'terminate',stamp+1)]),channel.name);call_records.ingest(payload([event(0)]),channel.name);frappe.db.commit()
  doc=frappe.get_doc('Relay Call',own.name);assert doc.state=='Ended' and not frappe.parse_json(doc.session)
  frappe.set_user(users[0]);call_records.record_outgoing({'to':'919000000000'},{'calls':[{'id':'outgoing-'+run}]},channel.name,contacts[0].name);frappe.db.commit()
  assert any(row.provider_id=='outgoing-'+run and row.direction=='Outgoing' for row in call_records.history(contacts[0].name)['items'])
  content=b'OggS'+b'fixture-audio-bytes'*4
  archived=call_records._store_recording(event(0)['id'],content)
  assert archived==call_records._store_recording(event(0)['id'],content)
  recording,returned=call_records.recording_content(archived['name']);assert returned==content
  private=frappe.get_doc('File',recording.file);assert private.is_private and private.attached_to_name==recording.name
  assert len(call_records.recordings(own.name))==1
  frappe.set_user(users[1]);denied(lambda:call_records.recording_content(archived['name']))
  frappe.set_user(users[0]);call_records.record_action({'action':'terminate','id':'outgoing-'+run},channel.name);frappe.db.commit()
  attempt,submit=call_records.admit_call({'to':'919000000000'},channel.name,contacts[0].name,'attempt-'+run);assert submit
  again,submit=call_records.admit_call({'to':'919000000000'},channel.name,contacts[0].name,'different-'+run);assert not submit and again.name==attempt.name
  assert call_records.pending_call()['outcome_unknown']
  outgoing=event(0);outgoing.update(id='recovered-'+run,direction='BUSINESS_INITIATED',biz_opaque_callback_data='relay-call:'+'0'*64,session={'sdp_type':'answer','sdp':'v=0\r\nanswer'})
  call_records.ingest(payload([outgoing]),channel.name);frappe.db.commit();attempt.reload();assert attempt.state=='Uncertain'
  outgoing['biz_opaque_callback_data']='relay-call:'+attempt.request_key
  call_records.ingest(payload([outgoing]),channel.name);frappe.db.commit();attempt.reload();assert attempt.state=='Confirmed'
  assert call_records.pending_call()['calls'][0]['id']==outgoing['id']
  call_records.record_action({'action':'terminate','id':outgoing['id']},channel.name);frappe.db.commit();assert call_records.pending_call()=={}
  from relay_core.hub import HubError
  connect_calls=[]
  def failed_execute(value):
   if value['operation']=='capabilities':return {'site':frappe.utils.get_url(),'calls':True}
   connect_calls.append(value);raise HubError('Synthetic lost acknowledgement')
  fake=Mock();fake.execute.side_effect=failed_execute
  prepared={'operation':'calls.action','action':'connect','to':'919000000000','sdp_type':'offer','sdp':'v=0\r\nfixture','request_key':'lost-'+run}
  with patch.object(whatsapp,'client',return_value=fake),patch.object(whatsapp,'prepare',side_effect=lambda *a,**kw:dict(prepared)):
   try:whatsapp.execute('calls.action',contact=people[0].name)
   except frappe.ValidationError:frappe.db.rollback()
   else:raise AssertionError('Lost acknowledgement was reported as successful')
   replay=whatsapp.execute('calls.action',contact=people[0].name)
   assert replay['outcome_unknown'] and len(connect_calls)==1
   assert connect_calls[0]['callback_data'].startswith('relay-call:') and 'request_key' not in connect_calls[0]
  terminated=event(0,'terminate');terminated.update(id='lost-ended-'+run,direction='BUSINESS_INITIATED',biz_opaque_callback_data=connect_calls[0]['callback_data'])
  call_records.ingest(payload([terminated]),channel.name);frappe.db.commit();assert call_records.pending_call()=={}
  prepared['request_key']='rejected-'+run
  def reject_execute(value):
   if value['operation']=='capabilities':return {'site':frappe.utils.get_url(),'calls':True}
   connect_calls.append(value);raise HubError('Synthetic rejection',{'provider':'WhatsApp','error':{'http_status':400,'outcome_unknown':False}})
  fake.execute.side_effect=reject_execute;count=len(connect_calls)
  with patch.object(whatsapp,'client',return_value=fake),patch.object(whatsapp,'prepare',side_effect=lambda *a,**kw:dict(prepared)):
   rejected=whatsapp.execute('calls.action',contact=people[0].name);again=whatsapp.execute('calls.action',contact=people[0].name)
   assert rejected['rejected'] and again==rejected and len(connect_calls)==count+1
  assert call_records.pending_call()=={}
  unresolved,submit=call_records.admit_call({'to':'919000000000'},channel.name,contacts[0].name,'manual-review-'+run);assert submit
  assert unresolved.name in [row.name for row in call_records.uncertain_attempts()['items']]
  assert not call_records.uncertain_attempts()['can_resolve']
  denied(lambda:call_records.resolve_attempt(unresolved.name,'Not started','Provider log confirms no call'))
  frappe.set_user('Administrator')
  resolved=call_records.resolve_attempt(unresolved.name,'Not started','Provider log confirms no call')
  assert resolved['state']=='Rejected'
  assert call_records.resolve_attempt(unresolved.name,'Not started','Provider log confirms no call')==resolved
  try:call_records.resolve_attempt(unresolved.name,'Not started','Different verification evidence')
  except frappe.ValidationError:frappe.db.rollback()
  else:raise AssertionError('Resolution evidence was overwritten')
  unresolved.reload();assert unresolved.resolved_by=='Administrator' and unresolved.resolved_at
  frappe.set_user(users[0])
  next_attempt,submit=call_records.admit_call({'to':'919000000000'},channel.name,contacts[0].name,'manual-link-'+run);assert submit
  call_records.record_outgoing({'to':'919000000000'},{'calls':[{'id':'manual-existing-'+run}]},channel.name,contacts[0].name);frappe.db.commit()
  frappe.set_user('Administrator')
  denied(lambda:call_records.resolve_attempt(next_attempt.name,'Existing call','Verified against provider records',provider_id=event(1)['id']))
  linked=call_records.resolve_attempt(next_attempt.name,'Existing call','Verified against provider records',provider_id='manual-existing-'+run)
  assert linked['state']=='Confirmed'
  assert call_records.resolve_attempt(next_attempt.name,'Existing call','Verified against provider records',provider_id='manual-existing-'+run)==linked
  frappe.set_user(users[0]);assert call_records.pending_call()['calls'][0]['id']=='manual-existing-'+run
  call_records.record_action({'action':'terminate','id':'manual-existing-'+run},channel.name);frappe.db.commit()
  assert call_records.pending_call()=={}
  print('PASS manager evidence resolution, immutable replay, unrelated-call denial, existing-call recovery and new admission after verified rejection')
  print('PASS durable call admission, reload-safe retry guard and exact webhook correlation without timing guesses')
  frappe.set_user('Administrator');teams.assign(contacts[0].name,assigned_to=users[1]);frappe.db.commit()
  frappe.set_user(users[0]);denied(lambda:call_records.history(contacts[0].name));denied(lambda:call_records.authorize({'action':'terminate','id':event(0)['id']}));denied(lambda:call_records.recording_content(archived['name']))
 print('PASS call projection deduplication, exact assignment signaling, no unrelated event data, termination ordering, outgoing history, private recording deduplication and revocation')
finally:frappe.destroy()
