"""Durable Telegram rejection and recovery against isolated Frappe database/Redis."""
import os,json,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from relay_core import inbox,messaging,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
try:
 assert messaging.action_error(frappe._dict(status='Dispatching',result=None)) is None
 stamp=str(time.time_ns());business=frappe.get_doc({'doctype':'Relay Inbox Simulation Business','title':'Typing '+stamp}).insert()
 person=frappe.get_doc({'doctype':'Contact','first_name':'Typing '+stamp,'links':[{'link_doctype':business.doctype,'link_name':business.name}]}).insert()
 contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Typing fixture'}).insert()
 channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Telegram','account':'typing-'+stamp,'enabled':1}).insert()
 endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'123456','verified':1}).insert()
 source=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'sender_endpoint':'123456','direction':'Incoming','status':'Sent','content':'Typing fixture','provider_context':json.dumps({'provider':'Telegram','chat_id':123456})}).insert();frappe.db.commit()
 source.provider_context=json.dumps({'provider':'Telegram','chat_id':123456,'message_id':10});source.save();frappe.db.commit()
 from relay_core.hub import HubError
 with patch.object(messaging,'connection_value',return_value=channel.account),patch.object(whatsapp,'client') as client:
  client.return_value.call_tool.side_effect=HubError('Hub connection is not authorized',{'provider':'Hub','error':{'http_status':401,'outcome_unknown':False}})
  denied=messaging.send(source.name,'text',{'text':'Denied fixture'},'denied-'+stamp)
  assert denied['status']=='Rejected' and 'not authorized' in denied['error']
  with patch.object(frappe,'publish_realtime') as publish:
   messaging.internal_save(frappe.get_doc('Relay Message Action',denied['action']))
   assert any(call.args==('relay_changed',{'kind':'message_actions'}) and call.kwargs=={'user':'Administrator','after_commit':True} for call in publish.call_args_list)
  denied_replay=messaging.send(source.name,'text',{'text':'Denied fixture'},'denied-'+stamp)
  assert denied_replay['status']=='Rejected' and 'not authorized' in denied_replay['error']
  assert client.return_value.call_tool.call_count==1
  snapshot=messaging.action_snapshots([denied['action'],denied['action']])
  assert len(snapshot['items'])==1 and snapshot['items'][0]['status']=='Rejected'
  assert client.return_value.call_tool.call_count==1, 'Reading socket-triggered action snapshots contacted Hub'
  restored=next(row for row in messaging.pending_messages(contact.name)['items'] if row['action']==denied['action'])
  assert restored['status']=='Failed' and 'not authorized' in restored['error']
  activity=next(row for row in messaging.actions(contact.name)['items'] if row['name']==denied['action'])
  assert activity['can_retry'] and 'not authorized' in activity['error']
  from relay_core import conversation_start
  with patch.object(conversation_start,'connection_value',return_value=channel.account):
   start=conversation_start.send(contact.name,endpoint.name,'text',{'text':'Denied start'},'start-'+stamp)
   assert start['status']=='Rejected' and 'not authorized' in start['error']
   calls=client.return_value.call_tool.call_count
   replay=conversation_start.send(contact.name,endpoint.name,'text',{'text':'Denied start'},'start-'+stamp)
   assert replay['status']=='Rejected' and 'not authorized' in replay['error']
   assert client.return_value.call_tool.call_count==calls
  client.return_value.call_tool.side_effect=TimeoutError('Lost response')
  pending=messaging.send(source.name,'text',{'text':'Recovered fixture'},'pending-'+stamp)
  assert pending['status']=='Uncertain'
  action=frappe.get_doc('Relay Message Action',pending['action'])
  client.reset_mock();client.return_value.call_tool.side_effect=None
  client.return_value.call_tool.return_value={'deliveries':[{'key':action.request_key,'operation':'telegram.message','state':'submitted','result':{'message_id':987654}}]}
  result=messaging.send(source.name,'text',{'text':'Recovered fixture'},'pending-'+stamp)
  assert result['status']=='Submitted' and frappe.get_doc('Relay Message',result['message']).content=='Recovered fixture'
  client.return_value.call_tool.assert_called_once_with('channels.deliveries',{'request_key':action.request_key})
  assert messaging.reconcile(action.name)['message']==result['message']
  assert frappe.db.count('Relay Message',{'source_key':action.request_key})==1
  client.return_value.call_tool.return_value={}
  reaction=messaging.send(source.name,'reaction',{'emoji':'👍'},'reaction-'+stamp)
  assert reaction['status']=='Uncertain'
  source.reload();assert not messaging.object_value(source.reactions or {}).get('bot')
  reaction_action=frappe.get_doc('Relay Message Action',reaction['action'])
  client.return_value.call_tool.return_value={'deliveries':[{'key':reaction_action.request_key,'operation':'telegram.message','state':'submitted','result':{'operation':'reaction','chat_id':123456,'message_id':10,'result':True}}]}
  before=frappe.db.count('Relay Message',{'relay_contact':contact.name})
  assert messaging.reconcile(reaction_action.name)['status']=='Submitted'
  source.reload();assert messaging.object_value(source.reactions or {})['bot']==[{'type':'emoji','emoji':'👍'}]
  assert messaging.reconcile(reaction_action.name)['status']=='Submitted'
  assert frappe.db.count('Relay Message',{'relay_contact':contact.name})==before
  from relay_core import telegram,telegram_delivery
  group_endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'-100123456','verified':1}).insert();frappe.db.commit()
  with patch.object(telegram,'connection_value',return_value=channel.account),patch.object(telegram_delivery,'connection_value',return_value=channel.account):
   client.return_value.call_tool.side_effect=TimeoutError('Group response lost')
   group=telegram.send(-100123456,'Group recovery fixture',reply_to=10,message_thread_id=7,request_key='group-'+stamp)
   assert group['status']=='Uncertain'
   action=frappe.get_doc('Relay Message Action',group['action'])
   client.reset_mock();client.return_value.call_tool.side_effect=None
   client.return_value.call_tool.return_value={'deliveries':[{'key':action.request_key,'operation':'telegram.message','state':'submitted','result':{'message_id':987655}}]}
   recovered=telegram.send(-100123456,'Group recovery fixture',reply_to=10,message_thread_id=7,request_key='group-'+stamp)
   assert recovered['status']=='Submitted'
   outgoing=frappe.get_doc('Relay Message',recovered['message'])
   ctx=messaging.object_value(outgoing.provider_context)
   assert outgoing.sender_endpoint=='-100123456' and ctx['message_thread_id']==7 and ctx['reply_to_message_id']==10
   client.return_value.call_tool.assert_called_once_with('channels.deliveries',{'request_key':action.request_key})
   assert messaging.reconcile(action.name)['message']==outgoing.name
   assert frappe.db.count('Relay Message',{'source_key':action.request_key})==1
   client.return_value.call_tool.side_effect=HubError('Denied',{'provider':'Hub','error':{'http_status':401,'outcome_unknown':False}})
   rejected=telegram.send(-100123456,'Group retry fixture',reply_to=11,message_thread_id=8,request_key='group-reject-'+stamp)
   assert rejected['status']=='Rejected'
   restored=telegram_delivery.pending(group_endpoint.name)
   assert [item['action'] for item in restored['items']]==[rejected['action']]
   assert restored['items'][0]['args']['message_thread_id']==8
   assert restored['items'][0]['args']['text']=='Group retry fixture'
   frappe.db.set_value('Relay Contact Endpoint',group_endpoint.name,'verified',0);frappe.db.commit()
   count=client.return_value.call_tool.call_count
   for operation in (lambda:messaging.reconcile(rejected['action']),lambda:messaging.retry(rejected['action']),lambda:telegram_delivery.pending(group_endpoint.name)):
    try:operation()
    except frappe.PermissionError:frappe.db.rollback()
    else:raise AssertionError('Revoked group binding was accepted')
   assert client.return_value.call_tool.call_count==count
   assert all(item['action']!=rejected['action'] for item in messaging.pending_messages(contact.name)['items'])
   frappe.db.set_value('Relay Contact Endpoint',group_endpoint.name,'verified',1);frappe.db.commit()
   client.return_value.call_tool.side_effect=None
   client.return_value.call_tool.return_value={'message_id':987656}
   retried=messaging.retry(rejected['action'])
   assert retried['status']=='Submitted'
   assert all(item['action']!=rejected['action'] for item in telegram_delivery.pending(group_endpoint.name)['items'])
   assert frappe.db.get_value('Relay Message Action',rejected['action'],'status')=='Rejected'
   sent_args=client.return_value.call_tool.call_args.args[1]
   assert sent_args['chat_id']==-100123456 and sent_args['reply_to']==11 and sent_args['message_thread_id']==8
   count=client.return_value.call_tool.call_count
   assert messaging.retry(rejected['action'])['message']==retried['message']
   assert client.return_value.call_tool.call_count==count
   page_names=[]
   for number in range(51):
    fixture=frappe.copy_doc(action)
    fixture.request_key=__import__('hashlib').sha256(('page-'+stamp+'-'+str(number)).encode()).hexdigest()
    fixture.status='Queued';fixture.outbound_message=None
    messaging.internal_save(fixture,new=True);page_names.append(fixture.name)
   frappe.db.commit()
   first=telegram_delivery.pending(group_endpoint.name)
   assert len(first['items'])==50 and first['next']
   second=telegram_delivery.pending(group_endpoint.name,before=first['next'])
   names=[item['action'] for item in first['items']+second['items']]
   assert set(page_names).issubset(names) and len(names)==len(set(names))
 from relay_core import channel_statuses
 with patch.object(channel_statuses,'connection_value',return_value=channel.account),patch.object(messaging,'connection_value',return_value=channel.account),patch.object(whatsapp,'client') as client:
  client.return_value.call_tool.side_effect=TimeoutError('Simulated lost acknowledgement')
  pending=messaging.send(source.name,'text',{'text':'Pushed receipt fixture'},'callback-'+stamp)
  receipt_action=frappe.get_doc('Relay Message Action',pending['action'])
  client.reset_mock()
  with patch.object(frappe,'enqueue'):
   event=frappe.get_doc({'doctype':'Relay Hub Event','event_key':'callback-'+stamp,'account':channel.account,'hub_event_id':'100','payload':'{}'}).insert()
  row={'id':100,'delivery_id':7,'request_key':receipt_action.request_key,'operation':'telegram.message','state':'submitted','receipt':{'message_id':987657,'chat_id':123456},'occurred_at':'2026-09-24T10:00:00Z'}
  channel_statuses.project_batch(event,[row]);frappe.db.commit()
  receipt_action.reload();assert receipt_action.status=='Submitted'
  assert frappe.db.count('Relay Message',{'source_key':receipt_action.request_key})==1
  message_before=frappe.db.get_value('Relay Message',receipt_action.outbound_message,'modified')
  channel_statuses.project_batch(event,[row,dict(row,id=99,state='uncertain',receipt={})]);frappe.db.commit()
  receipt_action.reload();assert receipt_action.status=='Submitted'
  assert frappe.db.count('Relay Message',{'source_key':receipt_action.request_key})==1
  assert frappe.db.get_value('Relay Message',receipt_action.outbound_message,'modified')==message_before
  client.return_value.call_tool.assert_not_called()
  assert frappe.session.user=='Administrator'
  def receipt_before_timeout(tool,args):
   raced=dict(row,id=101,request_key=args['request_key'],receipt={'message_id':987658,'chat_id':123456})
   channel_statuses.project_batch(event,[raced]);frappe.db.commit()
   raise TimeoutError('HTTP response lost after callback')
  client.return_value.call_tool.side_effect=receipt_before_timeout
  raced=messaging.send(source.name,'text',{'text':'Receipt race fixture'},'callback-race-'+stamp)
  assert raced['status']=='Submitted' and raced['message']
  assert frappe.db.get_value('Relay Message Action',raced['action'],'status')=='Submitted'
  print('PASS pushed Telegram receipts project once without Hub lookups and cannot regress submitted messages')
 expected=frappe.get_all('Relay Message Action',filters={'status':['in',['Dispatching','Queued','Uncertain']]},fields=['name'],order_by='modified asc, name asc',limit_page_length=30)
 assert [row.name for row in messaging.recovery_candidates()]==[row.name for row in expected]
 print('PASS Hub authentication rejection is definitive; Telegram journal recovery projects one message without resending')
finally:frappe.destroy()
