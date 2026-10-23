"""AI conversation summaries with a fixture model and real authorization/database."""
import os,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from frappe.permissions import add_permission
from relay_core import summaries,teams,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
frappe.reload_doc('relay_core','doctype','relay_conversation_summary',force=True)
frappe.reload_doc('relay_core','doctype','relay_message',force=True)
run=str(time.time_ns());actor='summary-executor@example.invalid';requester='relay-agent-a@example.invalid'
if not frappe.db.exists('User',actor):frappe.get_doc(dict(doctype='User',email=actor,first_name='Summary fixture',send_welcome_email=0,roles=[{'role':'Relay Communication Manager'}])).insert()
for doctype in ('Contact','Relay Inbox Simulation Business'):add_permission(doctype,'Relay Communication Manager',0)
business=frappe.get_doc({'doctype':'Relay Inbox Simulation Business','title':'Summary report '+run}).insert()
frappe.get_doc({'doctype':'User Permission','user':requester,'allow':business.doctype,
 'for_value':business.name,'apply_to_all_doctypes':1}).insert(ignore_permissions=True)
person=frappe.get_doc({'doctype':'Contact','first_name':'Summary report '+run,'links':[{'link_doctype':business.doctype,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Summary report '+run}).insert().name
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='summary-'+run,enabled=1)).insert()
provider=frappe.get_doc(dict(doctype='Relay AI Provider',provider='OpenAI',model='fixture',api_key='synthetic-key',enabled=1)).insert()
policy=frappe.get_doc(dict(doctype='Relay Automation Policy',channel=channel.name,provider=provider.name,execution_user=actor,business_doctype='Relay Inbox Simulation Business',enabled=1,mode='Shadow',daily_limit=100,allow_summary=1)).insert()
frappe.conf.relay_automation_enabled=0
source=frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact,channel=channel.name,direction='Incoming',
 content='Please check the installation tomorrow',status='Delivered',business_doctype=business.doctype,
 business_name=business.name)).insert()
teams.assign(contact,assigned_to=requester);frappe.db.commit();frappe.clear_cache()
expected={'overview':'Installation follow-up requested.','action_items':['Check installation tomorrow.'],'topics':[{'title':'Installation','messages':[source.name]}]}
def request(suffix):
 with patch.object(frappe,'enqueue'):
  return summaries.generate(None,channel.name,'30','summary-'+run+'-'+suffix,
   business_doctype=business.doctype,business_name=business.name)
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Unauthorized summary access')
try:
 frappe.set_user(requester)
 with patch.object(whatsapp,'client',side_effect=AssertionError('Summary cannot send messages')):
  queued=request('first');assert queued['status']=='Pending'
  assert request('first')['name']==queued['name']
  with patch.object(summaries,'complete_with_fallback',return_value=expected) as model:
   summaries.process(queued['name']);assert model.call_count==1
   summaries.process(queued['name']);assert model.call_count==1
  result=summaries.read(queued['name']);assert result['status']=='Ready' and result['result']==expected and result['message_count']==1,result
  frappe.set_user('relay-agent-b@example.invalid');denied(lambda:summaries.read(queued['name']))
  frappe.set_user('Administrator');frappe.db.set_value('Relay Message',source.name,'content','Installation cancelled');frappe.db.commit()
  frappe.set_user(requester);stale=summaries.read(queued['name']);assert stale['stale'] and stale['result'] is None
  invalid=request('invalid')
  with patch.object(summaries,'complete_with_fallback',return_value={**expected,'topics':[{'title':'Injected reference','messages':['RELAY-MSG-9999999999']}]}):summaries.process(invalid['name'])
  assert summaries.read(invalid['name'])['status']=='Failed'
  from relay_core import report_summaries,prepared_reports
  source.reload()
  report_rows=[{'message':source.name,'message_time':source.sent_at or source.creation,'relay_contact':contact,'channel':channel.name,
      'direction':source.direction,'content':source.content,'contact':'Fixture contact','business_records':'Fixture record','message_type':'text','status':'Delivered','attachments':''}]
  with patch.object(summaries,'complete_with_fallback',return_value=expected) as model:
   daily=report_summaries.summarize(report_rows)
   repeated=report_summaries.summarize(report_rows)
   assert model.call_count==1 and daily==repeated and daily[0]['sources']==[source.name]
   assert prepared_reports.source_names(daily)=={source.name}
   frappe.set_user('Administrator');frappe.db.set_value('Relay Message',source.name,'content','Daily source changed again');frappe.db.commit()
   frappe.set_user(requester);report_rows[0]['content']='Daily source changed again'
   changed=report_summaries.summarize(report_rows)
   assert model.call_count==2 and changed[0]['summary']!=daily[0]['summary']
  frappe.set_user('Administrator');frappe.db.set_value('Relay Message',source.name,'content','Retry daily summary source');frappe.db.commit()
  frappe.set_user(requester);report_rows[0]['content']='Retry daily summary source'
  with patch.object(summaries,'complete_with_fallback',side_effect=TimeoutError('Fixture timeout')) as model:
   try:report_summaries.summarize(report_rows)
   except frappe.ValidationError:pass
   else:raise AssertionError('Failed daily inference was reported ready')
   assert model.call_count==1
  with patch.object(summaries,'complete_with_fallback',return_value=expected) as model:
   retried=report_summaries.summarize(report_rows)
   assert model.call_count==1 and retried[0]['content'].startswith(expected['overview'])
   report_summaries.summarize(report_rows)
   assert model.call_count==1,'Ready daily summary was regenerated'
   assert frappe.db.get_value('Relay Conversation Summary',retried[0]['summary'],'attempts')==2
  from frappe.core.doctype.prepared_report import prepared_report as framework
  from io import BytesIO
  from openpyxl import load_workbook
  import json
  frappe.set_user('Administrator');frappe.reload_doc('relay_core','report','relay_communication_history',force=True)
  for output in ('PDF','Excel'):
   frappe.set_user(requester)
   values={'business_doctype':business.doctype,'business_name':business.name,'from_date':'1970-01-01','to_date':'2100-01-01','report_mode':'Daily summary','output_format':output}
   with patch.object(framework,'enqueue'):
    job=prepared_reports.request(values)['name']
   frappe.db.commit()
   with patch.object(summaries,'complete_with_fallback',return_value=expected):
    framework.generate_report(job)
   frappe.db.commit()
   state=prepared_reports.status(job)
   assert state['ready'],state
   data=json.loads(frappe.get_doc('Prepared Report',job).get_prepared_data())
   assert len(data['result'])==1 and data['result'][0]['sources']==[source.name]
   with patch.object(prepared_reports,'source_report',wraps=prepared_reports.source_report) as scan:
    raw=prepared_reports.download(job).get_data()
    assert scan.call_count==1,'Download repeated the full permission scan'
   if output=='PDF':assert raw.startswith(b'%PDF-')
   else:
    cells=list(load_workbook(BytesIO(raw),read_only=True).active.values)
    assert any(expected['overview'] in str(cell) for row in cells[1:] for cell in row)
    assert 'Source message count' in cells[0] and 'Source message references' in cells[0]
    assert str(cells[1][cells[0].index('Source message count')])=='1'
    assert cells[1][cells[0].index('Source message references')]==source.name
   frappe.set_user('Administrator');teams.assign(contact,assigned_to='relay-agent-b@example.invalid');frappe.db.commit()
   frappe.set_user(requester)
   with patch.object(summaries,'complete_with_fallback',side_effect=AssertionError('Download must not call AI')):
    denied(lambda:prepared_reports.download(job))
    assert prepared_reports.permission(frappe.get_doc('Prepared Report',job)) is False
   frappe.set_user('Administrator');teams.assign(contact,assigned_to=requester);frappe.db.commit()
   frappe.delete_doc('Prepared Report',job,ignore_permissions=True);frappe.db.commit()
  frappe.set_user(requester)
  with patch.object(summaries,'complete_with_fallback',side_effect=AssertionError('Missing policy cannot invoke model')):
   try:report_summaries.summarize([{**report_rows[0],'channel':'RELAY-CH-9999999999'}])
   except frappe.ValidationError:pass
   else:raise AssertionError('Summary report accepted an unconfigured channel')
  revoked=request('revoked');frappe.set_user('Administrator');teams.assign(contact,assigned_to='relay-agent-b@example.invalid');frappe.db.commit()
  with patch.object(summaries,'complete_with_fallback',side_effect=AssertionError('Revoked request cannot reach provider')) as model:
   summaries.process(revoked['name']);assert model.call_count==0
  assert frappe.db.get_value('Relay Conversation Summary',revoked['name'],'status')=='Failed'
 print('PASS queued summary/replay, period evidence, topic references, read-only result, edited-source invalidation, requester/actor permission checks and revoked request denied before inference')
finally:frappe.destroy()
