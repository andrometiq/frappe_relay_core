"""Observed forum names, replay ordering, directory scope and endpoint revocation."""
import os, time, hashlib, json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import telegram_topics as topics
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
channels=frappe.get_all('Relay Channel',filters={'channel':'Telegram','enabled':1},fields=['name','account'],order_by='name desc',limit_page_length=100)
channel=endpoint=None
for candidate in channels:
 name=frappe.db.get_value('Relay Contact Endpoint',{'channel':candidate.name,'verified':1,'endpoint':['like','-%']},'name')
 if name:channel=candidate;endpoint=frappe.get_doc('Relay Contact Endpoint',name);break
assert endpoint
chat=int(endpoint.endpoint);thread=int(time.time()*1000);stamp=int(time.time());key=hashlib.sha256(f'{channel.name}:{chat}:{thread}'.encode()).hexdigest()
def update(kind=None,title=None,date=stamp):
 message={'message_id':42,'date':date,'message_thread_id':thread,'chat':{'id':chat,'type':'supergroup','is_forum':True}}
 if kind:message[kind]={'name':title} if title else {}
 return {'channel':'Telegram','direction':'inbound','sender':str(chat),'provider_id':'123','body':'','payload':{'update_id':123,'message':message}}
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Expected denial')
event_name=None
try:
 with patch.object(topics,'connection_value',return_value=channel.account):
  topics.observe(update(),channel.name)
  from relay_core.automation import projection
  with patch.object(frappe,'enqueue'):
   event=frappe.get_doc({'doctype':'Relay Hub Event','event_key':'topic-fixture-'+str(thread),'account':channel.account,'hub_event_id':str(thread),'payload':json.dumps(update('forum_topic_created','Orders',stamp-10))}).insert()
   event_name=event.name;frappe.db.commit()
   projection.project(event.name);frappe.db.commit();projection.project(event.name)
  assert frappe.db.get_value('Relay Hub Event',event.name,'projection_status')=='Ignored'

  topics.observe(update('forum_topic_edited','Order updates',stamp+1),channel.name)
  topics.observe(update('forum_topic_created','Old name',stamp-10),channel.name)
  topics.observe(update('forum_topic_closed',date=stamp+2),channel.name)
  name=frappe.db.get_value('Relay Telegram Topic',{'topic_key':key},'name')
  assert frappe.db.count('Relay Telegram Topic',{'topic_key':key})==1
  row=frappe.get_doc('Relay Telegram Topic',name);assert row.title=='Order updates' and row.state=='Closed'
  page=topics.directory(channel.name,str(chat));assert any(r.name==name for r in page['items'])
  invalid=update('forum_topic_edited','Forged');invalid['sender']='-999'
  try:topics.observe(invalid,channel.name)
  except ValueError:pass
  else:raise AssertionError('Forged provenance accepted')
  topics.action('topics.reopen',{'chat_id':chat,'message_thread_id':thread},{'result':True})
  # Future fixture event time intentionally fences older local action timestamp.
  row.reload();assert row.state=='Closed'
  frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',0);frappe.db.commit()
  denied(lambda:topics.directory(channel.name,str(chat)))
  frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1);frappe.db.commit()
  frappe.set_user('relay-agent-a@example.invalid');denied(lambda:topics.directory(channel.name,str(chat)))
  frappe.set_user('Administrator')
  topics.remember(channel.name,chat,thread,state='Deleted',timestamp=frappe.utils.add_to_date(row.last_event_at,seconds=1))
  assert not any(r.name==name for r in topics.directory(channel.name,str(chat))['items'])
 print('PASS observed topic identity, late name discovery, stale event protection, closed/deleted state, forged identity, verified endpoint and manager boundaries')
finally:
 frappe.set_user('Administrator');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1)
 name=frappe.db.get_value('Relay Telegram Topic',{'topic_key':key},'name')
 if name:frappe.delete_doc('Relay Telegram Topic',name,ignore_permissions=True)
 if event_name:frappe.delete_doc('Relay Hub Event',event_name,ignore_permissions=True)
 frappe.db.commit();frappe.destroy()
