"""Ticket assignment, subscriber ownership and durable notification retries."""
import os,time
from unittest.mock import patch
from pathlib import Path
import frappe
from relay_core import tickets, ticket_notifications as notifications, teams, email, telegram
sites=Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites);frappe.init(site='relay-ai-test.local');frappe.connect()
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.set_user('Administrator');frappe.flags.mute_emails=True
run=str(time.time_ns());user='relay-agent-a@example.invalid';other='relay-agent-b@example.invalid'
business_type='Relay Inbox Simulation Business'
business=frappe.get_doc({'doctype':business_type,'title':'Notification '+run}).insert()
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
  return {'message_id':'<fixture@example.invalid>'}
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
 with patch.object(telegram,'send',return_value={'message_id':1}) as send:
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
finally:
 queue_patch.stop()
 frappe.db.rollback();frappe.destroy()
