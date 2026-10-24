"""Email scope, MIME arguments, signatures and automatic-reply safety in fixture DB."""
import base64
import json
import time
from unittest.mock import patch
import frappe
from channel_site_fixtures import init, business as fixture_business, user as fixture_user, push_status
from relay_core import email,email_preferences,messaging,attachments
init()
stamp=str(time.time_ns());actor='relay-mail-executor@example.invalid'
fixture_user(actor,manager=True)
business=fixture_business('Mail '+stamp);business_type=business.doctype
person=frappe.get_doc({'doctype':'Contact','first_name':'Mail '+stamp,'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Mail '+stamp}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Email','account':'mail-'+stamp,'enabled':1}).insert()
address='sender-'+stamp+'@example.invalid'
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':address,'verified':1}).insert()
context={'provider':'Email','message_id':'<source@example.invalid>','references':['<root@example.invalid>'],'subject':'Question','auto_submitted':False,'authentication':{'status':'pass'}}
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
  alias='alias-00-'+stamp+'@example.invalid'
  identifier='<dsn-'+stamp+'@example.invalid>'
  client.return_value.call_tool.return_value={'sent':True,'message_id':identifier}
  dsn_send=email.send([address],'Local DSN quantity 25','Delivery evidence',cc=[alias],message=source.name,request_key='dsn-'+stamp)
  dsn_action=frappe.get_doc('Relay Message Action',dsn_send['action'])
  client.reset_mock()
  def evidence(number,recipient,state,code):
   return dict(id=number,delivery_id=1001,request_key=dsn_action.request_key,operation='email.send',state=state,
    receipt=dict(message_id=identifier,recipient=recipient,delivery_status=state,status_code=code),occurred_at='2026-10-24T00:00:00Z')
  bounce=evidence(1002,address,'bounced','5.1.1')
  for row,expected in ((bounce,'Failed'),(bounce,'Failed'),(evidence(1001,address,'delayed','4.2.0'),'Failed'),
                       (evidence(1003,alias,'delivered','2.0.0'),'Failed'),(evidence(1004,address,'delivered','2.0.0'),'Delivered'),
                       (evidence(1005,address,'bounced','5.1.1'),'Delivered')):
   push_status(channel.account,[row])
   assert frappe.db.get_value('Relay Message',dsn_send['message'],'status')==expected
   dsn_action.reload();assert dsn_action.status=='Submitted'
  assert len(messaging.object_value(dsn_action.result)['_relay_email_receipts'])==2
  client.return_value.call_tool.assert_not_called()
  print('PASS signed DSN bounce, replay, delay ordering, recipient-specific evidence and positive delivery precedence')
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
  client.return_value.call_tool.side_effect=None
  client.return_value.call_tool.return_value={'deliveries':[]}
  assert messaging.reconcile(unknown['action'])['status']=='Uncertain'
  assert email.send([address],'Uncertain','Preserve this pending email',message=source.name,request_key='unknown-'+stamp)['action']==unknown['action']
  assert [call.args[0] for call in client.return_value.call_tool.call_args_list]==['email.send','channels.deliveries','channels.deliveries']
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
  before=frappe.db.count('Relay Message Action',{'source_message':source.name})
  for values in ({'to':[]},{'to':[address],'cc':'invalid'},{'to':[address],'bcc':['invalid']}):
   try:email.send(**values,subject='Malformed',body='Quantity 25',message=source.name)
   except ValueError:pass
   else:raise AssertionError('Malformed recipients were journaled')
  assert frappe.db.count('Relay Message Action',{'source_message':source.name})==before
  from relay_core.automation.service import internal_save
  malformed=frappe.copy_doc(frappe.get_doc('Relay Message Action',failed['action']))
  malformed.request_key='malformed-'+stamp
  payload=messaging.object_value(malformed.payload);payload['email_values']['to']=[]
  malformed.payload=json.dumps(payload);internal_save(malformed,new=True);frappe.db.commit()
  restored=messaging.pending_messages(contact.name)['items']
  assert any(row['action']==unknown['action'] for row in restored)
  assert not any(row['action']==malformed.name for row in restored)
  assert any(row['name']==malformed.name for row in messaging.actions(contact.name)['items'])
  print('PASS malformed recipients cannot create new attempts or break pending/history reads')
  from relay_core import channel_statuses
  with patch.object(channel_statuses,'connection_value',return_value=channel.account):
   frappe.set_user('Administrator')
   attempted=frappe.get_doc('Relay Message Action',unknown['action'])
   receipt={'id':200,'delivery_id':10,'request_key':attempted.request_key,'operation':'email.send','state':'submitted','receipt':{'sent':True,'message_id':'<pushed-'+stamp+'@example.invalid>'},'occurred_at':'2026-09-24T10:00:00Z'}
   client.reset_mock();push_status(channel.account,[receipt]);frappe.db.commit()
   attempted.reload();assert attempted.status=='Submitted' and attempted.outbound_message
   outgoing=frappe.get_doc('Relay Message',attempted.outbound_message)
   assert outgoing.content=='Preserve this pending email' and outgoing.owner==actor
   assert messaging.object_value(outgoing.message_data)['email']['to']==[address]
   before=outgoing.modified
   push_status(channel.account,[receipt]);frappe.db.commit();outgoing.reload()
   assert outgoing.modified==before
   client.return_value.call_tool.assert_not_called()
   assert frappe.session.user=='Administrator'
   frappe.set_user(actor)
   def receipt_then_timeout(tool,args):
    push_status(channel.account,[dict(receipt,id=201,request_key=args['request_key'],receipt={'sent':True,'message_id':'<race-'+stamp+'@example.invalid>'})]);frappe.db.commit()
    raise TimeoutError('Response lost after receipt callback')
   client.return_value.call_tool.side_effect=receipt_then_timeout
   raced=email.send([address],'Race','Callback race fixture',message=source.name,request_key='mail-race-'+stamp)
   assert raced['status']=='Submitted' and raced['message']
   client.return_value.call_tool.side_effect=None
   print('PASS pushed email receipts recover history without sending again, preserve owner, deduplicate and win timeout races')
  # Standalone sends use the same durable journal and request-key lookup.
  client.return_value.call_tool.side_effect=SystemExit('Crash before email Hub admission')
  try:email.send([address],'Standalone quantity 25','Recover exactly once',request_key='standalone-'+stamp)
  except SystemExit:pass
  key=__import__('hashlib').sha256(('email:'+actor+':standalone-'+stamp).encode()).hexdigest()
  standalone=frappe.get_doc('Relay Message Action',{'request_key':key})
  assert standalone.status=='Dispatching' and not standalone.source_message
  client.reset_mock();client.return_value.call_tool.side_effect=[{'deliveries':[]},{'pending':True,'state':'queued','delivery_id':401,'request_key':key}]
  assert messaging.reconcile(standalone.name)['status']=='Queued'
  assert any(row['action']==standalone.name for row in messaging.pending_messages(contact.name)['items'])
  assert [c.args[0] for c in client.return_value.call_tool.call_args_list]==['channels.deliveries','email.send']
  assert client.return_value.call_tool.call_args.args[1]['request_key']==key
  client.reset_mock();client.return_value.call_tool.side_effect=None
  client.return_value.call_tool.return_value={'deliveries':[{'key':key,'operation':'email.send','state':'submitted','result':{'sent':True,'message_id':'<standalone-'+stamp+'@example.invalid>'}}]}
  recovered=messaging.reconcile(standalone.name)
  assert recovered['status']=='Submitted' and recovered['message']
  client.return_value.call_tool.assert_called_once_with('channels.deliveries',{'request_key':key})
  assert messaging.action_snapshots([standalone.name])['items'][0]['status']=='Submitted'
  assert email.send([address],'Standalone quantity 25','Recover exactly once',request_key='standalone-'+stamp)['message']==recovered['message']
  assert frappe.db.count('Relay Message',{'source_key':key})==1
  client.return_value.call_tool.assert_called_once()
  def callback_then_pending(tool,args):
   push_status(channel.account,[{'id':402,'delivery_id':402,'request_key':args['request_key'],'operation':'email.send',
    'state':'submitted','receipt':{'sent':True,'message_id':'<standalone-race-'+stamp+'@example.invalid>'},'occurred_at':'2026-10-24T10:00:00Z'}])
   return {'pending':True,'state':'dispatching'}
  client.return_value.call_tool.side_effect=callback_then_pending
  raced=email.send([address],'Standalone race','Callback precedes pending',request_key='standalone-race-'+stamp)
  assert raced['status']=='Submitted' and raced['message']
  raced_action=frappe.get_doc('Relay Message Action',raced['action'])
  push_status(channel.account,[{'id':401,'delivery_id':402,'request_key':raced_action.request_key,'operation':'email.send',
   'state':'rejected','receipt':{},'occurred_at':'2026-10-24T10:00:00Z'}])
  raced_action.reload();assert raced_action.status=='Submitted' and raced_action.outbound_message==raced['message']
  def rejected_then_pending(tool,args):
   push_status(channel.account,[{'id':403,'delivery_id':403,'request_key':args['request_key'],'operation':'email.send',
    'state':'rejected','receipt':{},'occurred_at':'2026-10-24T10:00:00Z'}])
   return {'pending':True,'state':'queued'}
  client.return_value.call_tool.side_effect=rejected_then_pending
  assert email.send([address],'Rejected race','Rejection precedes pending',request_key='rejected-race-'+stamp)['status']=='Rejected'
  # Uncertainty and missing/invalid lookup responses never authorize resubmission.
  client.return_value.call_tool.side_effect=TimeoutError('Unknown SMTP outcome')
  uncertain=email.send([address],'Standalone uncertain','Keep original key',request_key='standalone-uncertain-'+stamp)
  client.reset_mock();client.return_value.call_tool.side_effect=None;client.return_value.call_tool.return_value={'deliveries':[]}
  assert messaging.reconcile(uncertain['action'])['status']=='Uncertain'
  assert client.return_value.call_tool.call_args.args[0]=='channels.deliveries'
  client.return_value.call_tool.return_value={}
  try:messaging.reconcile(uncertain['action'])
  except ValueError:pass
  else:raise AssertionError('Malformed lookup accepted')
  assert all(c.args[0]=='channels.deliveries' for c in client.return_value.call_tool.call_args_list)
  # Independent DB connections load the same action before either saves it.
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier, Event, local
  from relay_core.automation import service
  test_site,test_sites=frappe.local.site,frappe.local.sites_path
  for winner_status in ('Queued','Uncertain'):
   client.return_value.call_tool.side_effect=SystemExit('Crash before competing recovery')
   request='competing-'+winner_status+'-'+stamp
   try:email.send([address],'Competing recovery','Quantity 25',request_key=request)
   except SystemExit:pass
   key=__import__('hashlib').sha256(('email:'+actor+':'+request).encode()).hexdigest()
   name=frappe.db.get_value('Relay Message Action',{'request_key':key},'name');frappe.db.commit()
   barrier=Barrier(2);finished=Event();worker=local();conflicts=[]
   prepare=email.prepare;save=service.internal_save
   def competing_prepare(**values):
    args=prepare(**values);barrier.wait(timeout=15)
    if worker.stale:
     assert finished.wait(15), 'Winning worker did not finish'
     # End the read snapshot while retaining the stale Document, so Frappe's
     # timestamp check observes the committed winner on either DB isolation mode.
     frappe.db.rollback()
    return args
   def tracked_save(doc,*args,**kwargs):
    try:return save(doc,*args,**kwargs)
    except frappe.TimestampMismatchError:
     conflicts.append(doc.name);raise
   def provider(tool,args):
    if tool=='channels.deliveries':return {'deliveries':[]}
    assert tool=='email.send' and args['request_key']==key
    if winner_status=='Uncertain':raise TimeoutError('SMTP outcome unknown')
    return {'pending':True,'state':'queued'}
   def recovery(stale):
    worker.stale=stale
    frappe.init(site=test_site,sites_path=test_sites)
    frappe.connect();frappe.set_user(actor);frappe.flags.mute_emails=True;frappe.conf.relay_automation_enabled=0
    try:return messaging.reconcile(name)
    finally:
     if not stale:finished.set()
     frappe.destroy()
   client.reset_mock();client.return_value.call_tool.side_effect=provider
   with patch.object(email,'prepare',side_effect=competing_prepare),patch.object(service,'internal_save',side_effect=tracked_save):
    with ThreadPoolExecutor(max_workers=2) as pool:
     winner=pool.submit(recovery,False);stale=pool.submit(recovery,True)
     assert winner.result(timeout=30)['status']==winner_status
     assert stale.result(timeout=30)['status']==winner_status
   assert conflicts==[name]
   assert len([c for c in client.return_value.call_tool.call_args_list if c.args[0]=='email.send'])==1
   frappe.db.rollback()
   assert frappe.db.get_value('Relay Message Action',name,'status')==winner_status
   try:messaging.retry(name)
   except frappe.PermissionError:frappe.db.rollback()
   else:raise AssertionError('Competing recovery authorized a fresh retry key')
  print('PASS competing email workers preserve Queued/Uncertain outcomes after real timestamp conflicts; one send, no retry')
  client.return_value.call_tool.side_effect=SystemExit('Crash before revoked admission')
  try:email.send([address],'Revoked recovery','Do not send',request_key='standalone-revoked-'+stamp)
  except SystemExit:pass
  revoke_key=__import__('hashlib').sha256(('email:'+actor+':standalone-revoked-'+stamp).encode()).hexdigest()
  revoked=frappe.get_doc('Relay Message Action',{'request_key':revoke_key})
  frappe.set_user('Administrator');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',0);frappe.db.commit();frappe.set_user(actor)
  client.reset_mock()
  try:messaging.reconcile(revoked.name)
  except frappe.PermissionError:frappe.db.rollback()
  else:raise AssertionError('Revoked standalone recipient admitted')
  client.return_value.call_tool.assert_not_called()
  frappe.set_user('Administrator');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1);frappe.db.commit();frappe.set_user(actor)
  client.return_value.call_tool.side_effect=None
  print('PASS unanchored email journal, crash recovery, Hub lookup, pending receipts, monotonic callbacks and revoked recipients')
  context['auto_submitted']=True;frappe.set_user('Administrator');frappe.db.set_value('Relay Message',source.name,'provider_context',json.dumps(context));frappe.db.commit();client.reset_mock()
  email_preferences.auto_reply(source.name);client.return_value.call_tool.assert_not_called()
  context['auto_submitted']=False;frappe.db.set_value('Relay Message',source.name,'provider_context',json.dumps(context));endpoint.reload();endpoint.verified=0;endpoint.save();frappe.db.commit();client.reset_mock()
  with patch.object(frappe,'log_error'):email_preferences.auto_reply(source.name)
  client.return_value.call_tool.assert_not_called()
  print('PASS automated mail and revoked recipients cannot trigger automatic replies')
 from channel_site_fixtures import check_business_lifecycle
 check_business_lifecycle(business)
 print('PASS business update and delete/cancel link guards remain independent of Relay history')
 from channel_email_cases import run as channel_email_cases
 channel_email_cases()
finally:frappe.destroy()
