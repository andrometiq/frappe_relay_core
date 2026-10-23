"""Email scope, MIME arguments, signatures and automatic-reply safety in fixture DB."""
import base64
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from frappe.permissions import add_permission
from relay_core import email,email_preferences,messaging,attachments
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
stamp=str(time.time_ns());actor='relay-mail-executor@example.invalid'
if not frappe.db.exists('User',actor):frappe.get_doc({'doctype':'User','email':actor,'first_name':'Mail fixture','send_welcome_email':0,'roles':[{'role':'Relay Communication Manager'},{'role':'Relay Communication User'}]}).insert()
business_type='Relay Inbox Simulation Business'
assert frappe.db.exists('DocType',business_type)
add_permission('Contact','Relay Communication Manager',0)
business=frappe.get_doc({'doctype':business_type,'title':'Mail '+stamp}).insert()
person=frappe.get_doc({'doctype':'Contact','first_name':'Mail '+stamp,'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Mail '+stamp}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Email','account':'mail-'+stamp,'enabled':1}).insert()
address='sender-'+stamp+'@example.invalid'
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':address,'verified':1}).insert()
context={'provider':'Email','message_id':'<source@example.invalid>','references':['<root@example.invalid>'],'subject':'Question','auto_submitted':False}
source=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'sender_endpoint':address,'direction':'Incoming','content':'Question','status':'Sent','message_type':'text','provider_context':json.dumps(context),'message_data':json.dumps({'kind':'text','text':'Question','email':{'subject':'Question','attachments':[{'filename':'document.pdf'}]}}),'provider_id':'fixture-mail-'+stamp}).insert()
rule=frappe.get_doc({'doctype':'Relay Email Rule','channel':channel.name,'enabled':1,'execution_user':actor,'subject':'Request received','body':'An agent will review your request.'}).insert()
frappe.db.commit()
try:
 frappe.set_user(actor)
 email_preferences.save('Synthetic signature');frappe.db.commit()
 assert email_preferences.read()['signature']=='Synthetic signature'
 frappe.set_user('Administrator');assert email_preferences.read()['signature']!='Synthetic signature';frappe.set_user(actor)
 print('PASS signatures are persisted and private to their user')
 with patch.object(email,'connection_value',return_value=channel.account),patch.object(messaging,'connection_value',return_value=channel.account),patch.object(email.whatsapp,'client') as client:
  assert email.recipient_options(source.name)==[{'value':address,'label':address}]
  assert email.recipient_options(source.name,'missing-address')==[]
  assert email.recipient_options(source.name,'%')==[]
  frappe.set_user('Administrator')
  for index in range(35):
   frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':f'alias-{index:02d}-{stamp}@example.invalid','verified':index!=34}).insert()
  frappe.db.commit();frappe.set_user(actor)
  assert len(email.recipient_options(source.name))==30
  assert len(email.recipient_options(source.name,'alias-33'))==1
  assert email.recipient_options(source.name,'alias-34')==[]
  print('PASS searchable email recipients are bounded, verified and server-filtered')
  client.return_value.call_tool.return_value={'sent':True,'message_id':'<outgoing-'+stamp+'@example.invalid>'}
  file=attachments.upload(source.name,'evidence.txt',base64.b64encode(b'Private evidence').decode());frappe.db.commit()
  sent=email.send([address],'Re: Question','Reply',message=source.name,html='<p>Reply</p>',attachment_ids=[file['name']],request_key='mail-'+stamp)
  tool,args=client.return_value.call_tool.call_args.args
  assert attachments.read(sent['message'],index=0).get_data()==b'Private evidence'
  client.reset_mock()
  assert email.send_status(source.name,'mail-'+stamp)=={'status':'Sent','message':sent['message']}
  assert email.send_status(source.name,'missing-'+stamp)=={'status':'Unconfirmed'}
  client.return_value.call_tool.assert_not_called()
  print('PASS email receipt checks read persisted history without sending again')

  assert email.send([address],'Re: Question','Reply',message=source.name,html='<p>Reply</p>',attachment_ids=[file['name']],request_key='mail-'+stamp)['message']==sent['message']
  frappe.db.set_value('Relay Message Action',sent['action'],{'status':'Dispatching','outbound_message':None});frappe.db.commit()
  assert messaging.reconcile(sent['action'])['message']==sent['message']
  client.return_value.call_tool.assert_not_called()
  assert tool=='email.send' and args['in_reply_to']=='<source@example.invalid>' and args['references']==['<root@example.invalid>','<source@example.invalid>']
  assert args['html']=='<p>Reply</p>' and base64.b64decode(args['attachments'][0]['content_base64'])==b'Private evidence'
  client.return_value.call_tool.return_value={'sent':True,'message_id':'<forward-'+stamp+'@example.invalid>'}
  email.send([address],'Fwd: Question','Forward',message=source.name,forward=1)
  assert 'in_reply_to' not in client.return_value.call_tool.call_args.args[1]
  print('PASS email reply threads and private attachments reach Hub; forwarding starts a separate thread')
  client.reset_mock();client.return_value.call_tool.return_value={'sent':True,'message_id':'<auto-'+stamp+'@example.invalid>'}
  email_preferences.auto_reply(source.name);email_preferences.auto_reply(source.name)
  calls=client.return_value.call_tool.call_args_list
  assert len(calls)==1 and calls[0].args[1]['auto_submitted'] is True
  print('PASS automatic reply replays use the same daily recipient key and automatic-response header')
  client.reset_mock();client.return_value.call_tool.side_effect=TimeoutError('fixture timeout')
  unknown=email.send([address],'Uncertain','Preserve this pending email',message=source.name,request_key='unknown-'+stamp)
  assert unknown['status']=='Uncertain' and client.return_value.call_tool.call_count==1
  pending=messaging.pending_messages(contact.name)['items']
  assert any(row['action']==unknown['action'] and row['status']=='Unconfirmed' for row in pending)
  assert messaging.reconcile(unknown['action'])['status']=='Uncertain'
  assert email.send([address],'Uncertain','Preserve this pending email',message=source.name,request_key='unknown-'+stamp)['action']==unknown['action']
  assert client.return_value.call_tool.call_count==1,'Replay or reconciliation repeated an uncertain email'
  try:email.send([address],'Changed','Different content',message=source.name,request_key='unknown-'+stamp)
  except ValueError:pass
  else:raise AssertionError('Email key allowed changed payload')
  client.return_value.call_tool.side_effect=None
  print('PASS durable uncertain email restores in inbox; reconcile/replay never resend; changed payload rejected')
  client.reset_mock()
  retry_address='retry-'+stamp+'@example.invalid'
  failed=email.send([retry_address],'Retry fixture','Previously invalid recipient',message=source.name,request_key='reject-'+stamp)
  assert failed['status']=='Rejected';client.return_value.call_tool.assert_not_called()
  assert any(row['name']==failed['action'] and row['can_retry'] for row in messaging.actions(contact.name)['items'])
  frappe.set_user('Administrator')
  frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':retry_address,'verified':1}).insert()
  frappe.db.commit();frappe.set_user(actor)
  client.return_value.call_tool.return_value={'sent':True,'message_id':'<retry-'+stamp+'@example.invalid>'}
  retried=messaging.retry(failed['action'])
  assert retried['status']=='Submitted' and retried['action']!=failed['action']
  assert messaging.retry(failed['action'])['action']==retried['action']
  assert client.return_value.call_tool.call_count==1
  try:messaging.retry(unknown['action'])
  except frappe.PermissionError:pass
  else:raise AssertionError('Uncertain email was retryable')
  print('PASS rejected email retry revalidates recipient, has stable child identity, and cannot retry uncertainty')
  from relay_core import channel_statuses
  with patch.object(channel_statuses,'connection_value',return_value=channel.account):
   frappe.set_user('Administrator')
   with patch.object(frappe,'enqueue'):
    event=frappe.get_doc({'doctype':'Relay Hub Event','event_key':'mail-status-'+stamp,'account':channel.account,'hub_event_id':'200','payload':'{}'}).insert()
   attempted=frappe.get_doc('Relay Message Action',unknown['action'])
   receipt={'id':200,'delivery_id':10,'request_key':attempted.request_key,'operation':'email.send','state':'submitted','receipt':{'sent':True,'message_id':'<pushed-'+stamp+'@example.invalid>'},'occurred_at':'2026-09-24T10:00:00Z'}
   client.reset_mock();channel_statuses.project_batch(event,[receipt]);frappe.db.commit()
   attempted.reload();assert attempted.status=='Submitted' and attempted.outbound_message
   outgoing=frappe.get_doc('Relay Message',attempted.outbound_message)
   assert outgoing.content=='Preserve this pending email' and outgoing.owner==actor
   assert messaging.object_value(outgoing.message_data)['email']['to']==[address]
   before=outgoing.modified
   channel_statuses.project_batch(event,[receipt]);frappe.db.commit();outgoing.reload()
   assert outgoing.modified==before
   client.return_value.call_tool.assert_not_called()
   assert frappe.session.user=='Administrator'
   frappe.set_user(actor)
   def receipt_then_timeout(tool,args):
    channel_statuses.project_batch(event,[dict(receipt,id=201,request_key=args['request_key'],receipt={'sent':True,'message_id':'<race-'+stamp+'@example.invalid>'})]);frappe.db.commit()
    raise TimeoutError('Response lost after receipt callback')
   client.return_value.call_tool.side_effect=receipt_then_timeout
   raced=email.send([address],'Race','Callback race fixture',message=source.name,request_key='mail-race-'+stamp)
   assert raced['status']=='Submitted' and raced['message']
   client.return_value.call_tool.side_effect=None
   print('PASS pushed email receipts recover history without sending again, preserve owner, deduplicate and win timeout races')
  context['auto_submitted']=True;frappe.set_user('Administrator');frappe.db.set_value('Relay Message',source.name,'provider_context',json.dumps(context));frappe.db.commit();client.reset_mock()
  email_preferences.auto_reply(source.name);client.return_value.call_tool.assert_not_called()
  context['auto_submitted']=False;frappe.db.set_value('Relay Message',source.name,'provider_context',json.dumps(context));endpoint.verified=0;endpoint.save();frappe.db.commit();client.reset_mock()
  with patch.object(frappe,'log_error'):email_preferences.auto_reply(source.name)
  client.return_value.call_tool.assert_not_called()
  print('PASS automated mail and revoked recipients cannot trigger automatic replies')
finally:frappe.destroy()
