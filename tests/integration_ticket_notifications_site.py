"""Ticket assignment, subscriber ownership and durable notification retries."""
from site_labels import run_label
import time
from unittest.mock import patch
import frappe
from relay_core import tickets, ticket_notifications as notifications, teams, email, telegram
from channel_site_fixtures import init, business as fixture_business, user as fixture_user
init()
run = run_label();user='relay-agent-a@example.invalid';other='relay-agent-b@example.invalid'
fixture_user(user);fixture_user(other)
business=fixture_business('Notification '+run);business_type=business.doctype
person=frappe.get_doc({'doctype':'Contact','first_name':'Notification '+run,'email_ids':[{'email_id':user,'is_primary':1}], 'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Notification '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Email','account':'notify-'+run,'enabled':1}).insert()
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':user,'verified':1}).insert()
message=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'direction':'Incoming','content':'Notification fixture','status':'Sent'}).insert()
team=teams.save('Notification '+run,[user,other]);teams.assign(contact.name,team['name'])
created=tickets.create('Notification '+run,[message.name]);frappe.db.commit()
queue_patch=patch.object(frappe,'enqueue');queue_patch.start()
def denied(fn):
 try:fn()
 except (frappe.PermissionError,frappe.ValidationError):frappe.db.rollback()
 else:raise AssertionError('Unauthorized operation accepted')
def pending():return frappe.get_all('Relay Ticket Notification',filters={'ticket':created['name'],'status':'Pending'},pluck='name')
try:
 tickets.assign(created['name'],user);frappe.db.commit()
 frappe.set_user(user);assert tickets.read(created['name'])['assigned_to']==user
 denied(lambda:tickets.assign(created['name'],other))
 notifications.subscribe(created['name'],endpoint.name)
 assert notifications.subscription(created['name'])['enabled']==1
 # Repeated integration runs can produce more than one page of owned endpoints.
 seen=set();after=None;found=False
 while True:
  page=notifications.destinations(after=after)
  assert len(page['items'])<=30
  values={row['value'] for row in page['items']}
  assert not seen.intersection(values)
  seen.update(values);found=found or endpoint.name in values
  if not page['next']:break
  assert page['next']!=after
  after=page['next']
 assert found, 'Owned endpoint missing from every destination page'
 frappe.set_user(other);denied(lambda:tickets.read(created['name']))
 frappe.set_user('Administrator');tickets.assign(created['name'],other);frappe.db.commit()
 frappe.set_user(other);denied(lambda:notifications.subscribe(created['name'],endpoint.name))
 frappe.set_user('Administrator');tickets.assign(created['name'],user);frappe.db.commit()
 # Pending historical assignment updates are still permission checked on delivery.
 for name in pending():frappe.db.set_value('Relay Ticket Notification',name,'status','Rejected')
 frappe.db.commit();frappe.set_user(user)
 with patch.object(frappe,'enqueue'):
  tickets.update_status(created['name'],'In progress');frappe.db.commit()
 names=pending();assert len(names)==1
 submitted=[]
 def fake_send(*args,**kwargs):
  submitted.append(kwargs['request_key'])
  if len(submitted)==1:raise RuntimeError('Synthetic connection lost after submission')
  return {'status':'Submitted','message_id':'<fixture@example.invalid>'}
 with patch.object(email,'send',side_effect=fake_send):
  notifications.dispatch(names[0]);assert frappe.db.get_value('Relay Ticket Notification',names[0],'status')=='Pending'
  notifications.dispatch(names[0]);notifications.dispatch(names[0])
 assert len(submitted)==2 and submitted[0]==submitted[1]
 assert frappe.db.get_value('Relay Ticket Notification',names[0],'status')=='Submitted'
 print('PASS assignment access, own-endpoint subscription, durable retry key and completed replay')
 with patch.object(frappe,'enqueue'):
  tickets.update_status(created['name'],'Resolved');frappe.db.commit()
 name=pending()[0];frappe.set_user('Administrator');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',0);frappe.db.commit()
 with patch.object(email,'send') as send:
  notifications.dispatch(name);send.assert_not_called()
 assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Rejected'
 frappe.set_user(user);notifications.subscribe(created['name'],enabled=0)
 assert not notifications.subscription(created['name'])['enabled']
 print('PASS revoked endpoint prevents delivery and still permits unsubscribe')
 frappe.set_user('Administrator');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1)
 wa=frappe.get_doc({'doctype':'Relay Channel','channel':'WhatsApp','account':'notify-'+run,'enabled':1}).insert()
 wae=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':wa.name,'relay_contact':contact.name,'endpoint':'15551234567','verified':1}).insert()
 frappe.db.commit();frappe.set_user(user);denied(lambda:notifications.subscribe(created['name'],wae.name))
 print('PASS WhatsApp ticket notification destination rejected')
 frappe.set_user('Administrator')
 tg=frappe.get_doc({'doctype':'Relay Channel','channel':'Telegram','account':'notify-'+run,'enabled':1}).insert()
 tge=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':tg.name,'relay_contact':contact.name,'endpoint':'123456789','verified':1}).insert()
 frappe.db.commit();frappe.set_user(user);notifications.subscribe(created['name'],tge.name)
 tickets.update_status(created['name'],'Open');frappe.db.commit();name=pending()[0]
 with patch.object(telegram,'send',return_value={'status':'Submitted','message_id':1}) as send:
  notifications.dispatch(name);notifications.dispatch(name)
  assert send.call_count==1 and send.call_args.args[0]==123456789
  assert send.call_args.kwargs['request_key'].startswith('ticket-')
 tickets.update_status(created['name'],'In progress');frappe.db.commit();name=pending()[0]
 frappe.set_user('Administrator');tickets.assign(created['name'],other);frappe.db.commit()
 with patch.object(telegram,'send') as send:
  notifications.dispatch(name);send.assert_not_called()
 assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Rejected'
 for name in pending():notifications.dispatch(name)
 print('PASS Telegram notification replay suppression and revoked ticket access blocks queued sends')
 from relay_core import messaging,telegram_delivery,whatsapp
 from channel_site_fixtures import push_status
 from contextlib import ExitStack
 frappe.set_user('Administrator');tickets.assign(created['name'],user);frappe.db.commit()
 for name in pending():frappe.db.set_value('Relay Ticket Notification',name,'status','Rejected')
 frappe.db.commit();frappe.set_user(user)
 with ExitStack() as stack:
  for module in (messaging,email,telegram,telegram_delivery):
   stack.enter_context(patch.object(module,'connection_value',return_value=channel.account))
  hub=stack.enter_context(patch.object(whatsapp,'client')).return_value
  current_status='In progress';sequence=500
  for medium,binding in [('Email',endpoint),('Telegram',tge)]:
   notifications.subscribe(created['name'],binding.name)
   for outcome in ('rejected','uncertain','pending','crash'):
    current_status='Open' if current_status!='Open' else 'In progress'
    tickets.update_status(created['name'],current_status);frappe.db.commit()
    name=pending()[0];sequence+=1
    def delivery(tool,args):
     if tool=='channels.deliveries':return {'deliveries':[]}
     if outcome=='uncertain':raise TimeoutError('Unknown provider acceptance')
     if outcome=='crash':raise SystemExit('Pre-admission crash')
     return {'delivery':{'state':'rejected'}} if outcome=='rejected' else {'pending':True,'state':'queued'}
    hub.call_tool.side_effect=delivery
    try:notifications.dispatch(name)
    except SystemExit:pass
    event_key=frappe.db.get_value('Relay Ticket Notification',name,'event_key')
    request_key=notifications.digest(*(['email',user,'ticket-'+event_key] if medium=='Email' else [user,'ticket-'+event_key]))
    action=frappe.get_doc('Relay Message Action',{'request_key':request_key})
    assert messaging.object_value(action.payload)['notification']==name
    expected='Rejected' if outcome=='rejected' else 'Pending'
    assert frappe.db.get_value('Relay Ticket Notification',name,'status')==expected
    hub.reset_mock();hub.call_tool.side_effect=None
    if outcome=='rejected':
     notifications.subscribe(created['name'],enabled=0)
     denied(lambda:messaging.retry(action.name))
     assert not next(row for row in messaging.actions(contact.name)['items'] if row['name']==action.name)['can_retry']
     notifications.subscribe(created['name'],binding.name,enabled=1)
     frappe.set_user('Administrator');tickets.assign(created['name'],other);frappe.db.commit();frappe.set_user(user)
     notifications.readable_contact(contact.name)
     denied(lambda:tickets.read(created['name']))
     denied(lambda:messaging.retry(action.name))
     hub.call_tool.assert_not_called()
     frappe.set_user('Administrator');tickets.assign(created['name'],user);frappe.db.commit()
     for extra in pending():frappe.db.set_value('Relay Ticket Notification',extra,'status','Rejected')
     frappe.db.commit();frappe.set_user(user)
    if outcome in ('pending','crash'):
     notifications.subscribe(created['name'],enabled=0)
     notifications.dispatch(name)
     assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Rejected'
     # Recovery of a journaled pre-Hub action must also honor the unsubscribe.
     if outcome=='crash':
      hub.call_tool.return_value={'deliveries':[]}
      try:messaging.reconcile(action.name)
      except frappe.PermissionError:frappe.db.rollback()
      action.reload()
      assert all(c.args[0]=='channels.deliveries' for c in hub.call_tool.call_args_list)
     else:hub.call_tool.assert_not_called()
     # Further ticket changes while revoked cannot create notification work.
     count=frappe.db.count('Relay Ticket Notification',{'ticket':created['name']})
     current_status='Open' if current_status!='Open' else 'In progress'
     tickets.update_status(created['name'],current_status);frappe.db.commit()
     assert frappe.db.count('Relay Ticket Notification',{'ticket':created['name']})==count
     notifications.subscribe(created['name'],binding.name,enabled=1)
     continue
    receipt={'message_id':'<notification-'+run+'-'+str(sequence)+'@example.invalid>','sent':True} if medium=='Email' else {'chat_id':123456789,'message_id':sequence}
    row={'id':sequence,'delivery_id':sequence,'request_key':request_key,'operation':'email.send' if medium=='Email' else 'telegram.message',
     'state':'submitted','receipt':receipt,'occurred_at':'2026-10-24T10:00:00Z'}
    push_status(channel.account,[row])
    assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Submitted'
    action.reload();assert action.status=='Submitted' and action.outbound_message
    push_status(channel.account,[dict(row,id=sequence-1,state='rejected',receipt={})])
    notifications.dispatch(name);hub.call_tool.assert_not_called()
    notifications.set_outcome(name,'Rejected')
    notifications.defer(frappe.get_doc('Relay Ticket Notification',name))
    notice=frappe.get_doc('Relay Ticket Notification',name)
    assert notice.status=='Submitted' and not notice.reason and not notice.next_attempt
  print('PASS real Telegram/email notification journals: rejection, uncertainty, late success, pending, admission crash and revocation')
  print('PASS email/Telegram notification retries refuse unsubscribe and ticket revocation despite retained contact access')
  notifications.subscribe(created['name'],endpoint.name)
  for state,expected in [('submitted','Submitted'),('queued','Queued'),('uncertain','Uncertain'),('rejected','Rejected')]:
   current_status='Open' if current_status!='Open' else 'In progress'
   tickets.update_status(created['name'],current_status);frappe.db.commit()
   name=pending()[0];notice=frappe.get_doc('Relay Ticket Notification',name)
   raw_key='ticket-'+notice.event_key
   hashed=notifications.digest('email',user,raw_key)
   assert not frappe.db.exists('Relay Message Action',{'request_key':['in',[raw_key,hashed]]})
   receipt={'sent':True,'message_id':'<legacy-'+state+'-'+run+'@example.invalid>'}
   def legacy_lookup(tool,args):
    assert tool=='channels.deliveries' and args=={'request_key':raw_key}, 'Legacy notification was sent again'
    return {'deliveries':[{'key':raw_key,'operation':'email.send','state':state,'result':receipt}]}
   hub.reset_mock();hub.call_tool.side_effect=legacy_lookup
   notifications.dispatch(name)
   action=frappe.get_doc('Relay Message Action',{'request_key':raw_key})
   assert action.status==expected and messaging.object_value(action.payload)['notification']==name
   assert not frappe.db.exists('Relay Message Action',{'request_key':hashed})
   notifications.dispatch(name)
   action.reload();assert action.status==expected
   if state=='submitted':
    assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Submitted'
    assert frappe.db.count('Relay Message',{'source_key':raw_key})==1
    hub.call_tool.assert_called_once_with('channels.deliveries',{'request_key':raw_key})
   if state in ('queued','uncertain'):
    sequence+=1
    push_status(channel.account,[{'id':sequence,'delivery_id':sequence,'request_key':raw_key,'operation':'email.send',
     'state':'submitted','receipt':receipt,'occurred_at':'2026-10-24T10:00:00Z'}])
    assert frappe.db.get_value('Relay Ticket Notification',name,'status')=='Submitted'
  print('PASS legacy unjournaled notifications adopt raw provider keys for accepted/pending/uncertain/rejected intents without resending')

 from channel_notification_cases import run as shared_identity_notifications
 shared_identity_notifications()
 shared_identity_notifications(separate_contact=True)

finally:
 queue_patch.stop()
 frappe.db.rollback();frappe.destroy()
