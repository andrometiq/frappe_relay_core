"""Opt-in real Frappe/Postgres integration tests using synthetic data only.

Run with the Frappe environment Python; model and transport are stubbed.
Requires an already installed isolated relay-ai-test.local site.
"""
import os,pathlib,json
from unittest.mock import patch
sites=os.environ.get('RELAY_AUTOMATION_TEST_SITES')
if not sites:
 raise SystemExit('Set RELAY_AUTOMATION_TEST_SITES to the isolated automation test sites directory')
os.chdir(sites)
import frappe
frappe.init(site='relay-ai-test.local');frappe.connect();frappe.set_user('Administrator')
assert frappe.conf.db_name == 'relay_ai_test_20260922', 'Refusing a non-test database'
if not frappe.get_meta('Relay Message').has_field('message_data') or not frappe.get_meta('Relay Message').has_field('provider_message_key'):
 frappe.reload_doc('relay_core','doctype','relay_message',force=True)
if not frappe.get_meta('Relay Automation Run').has_field('message_hash'):
 frappe.reload_doc('relay_core','doctype','relay_automation_run',force=True)
frappe.db.commit()
frappe.flags.mute_emails=True
from relay_core.automation import service
from relay_core.automation.contracts import action_key
# Only synthetic data in the dedicated relay_ai_test_20260922 database.
user='automation-test@example.invalid'
if not frappe.db.exists('User',user):
 frappe.get_doc(dict(doctype='User',email=user,first_name='Relay automation test',send_welcome_email=0,roles=[{'role':'Relay Communication Manager'}])).insert()
from frappe.permissions import add_permission
add_permission('Contact','Relay Communication Manager',0)
frappe.db.commit()
if not frappe.db.exists('DocType','Relay Test Business'):
 frappe.get_doc(dict(doctype='DocType',name='Relay Test Business',module='Relay Core',custom=1,autoname='field:title',fields=[dict(fieldname='title',label='Title',fieldtype='Data',reqd=1)],permissions=[dict(role='Relay Communication Manager',read=1,write=1,create=1),dict(role='System Manager',read=1,write=1,create=1)])).insert()
if not frappe.db.exists('Relay Test Business','Synthetic Customer'):
 frappe.get_doc(dict(doctype='Relay Test Business',title='Synthetic Customer')).insert()
contact=frappe.get_doc(dict(doctype='Contact',first_name='Synthetic',last_name='Contact',phone_nos=[dict(phone='919000000001',is_primary_mobile_no=1)],links=[dict(link_doctype='Relay Test Business',link_name='Synthetic Customer')])).insert()
relay_contact=frappe.get_doc(dict(doctype='Relay Contact',contact=contact.name,display_name='Synthetic Contact')).insert()
# The isolated site may be reused across runs. Reset only this synthetic
# fixture's automation ownership state; no business records are touched.
relay_contact.automation_paused=0
relay_contact.automation_generation=int(relay_contact.automation_generation or 0)+1
relay_contact.save(ignore_permissions=True)
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='synthetic-account',enabled=1)).insert()
frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint='919000000001',relay_contact=relay_contact.name,verified=1)).insert()
provider=frappe.get_doc(dict(doctype='Relay AI Provider',provider='OpenRouter',model='fixture-model',api_key='not-a-real-key',enabled=1)).insert()
reply=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Acknowledgement',channel='WhatsApp',language='English',body='Our team will contact you soon.',ai_enabled=1,published=1)).insert()
policy=frappe.get_doc(dict(doctype='Relay Automation Policy',channel=channel.name,provider=provider.name,execution_user=user,enabled=1,mode='Automatic',allow_ticket=1,allow_reply=1,business_doctype='Relay Test Business',daily_limit=100,reply_ids=reply.name,fallback_reply=reply.name)).insert()
frappe.db.commit()
frappe.conf.relay_automation_enabled=1
counter=0
def message():
 global counter
 counter+=1
 with patch.object(frappe,'enqueue'):
  doc=frappe.get_doc(dict(doctype='Relay Message',relay_contact=relay_contact.name,channel=channel.name,content='Please help with my payment screenshot',direction='Incoming',sender_endpoint='919000000001',source_key=f'{channel.name}-{counter}')).insert()
 frappe.db.commit()
 return doc

def decision(**kw):return dict(category='Payment evidence',brief='Review payment evidence',create_ticket=True,reply=reply.name,handoff=False)|kw

def process(doc,value):
 name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
 with patch.object(service,'complete',return_value=value),patch.object(frappe,'enqueue'):
  service.process(name)
 return frappe.get_doc('Relay Automation Run',name)

m=message();r=process(m,decision());assert r.status=='Completed',(r.status,r.reason)
assert frappe.db.count('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})==1
with patch.object(frappe,'enqueue'):
 assert service.create_run(m)['name']==r.name
process(m,decision())
assert frappe.db.count('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})==1
out=frappe.db.get_value('Relay Automation Outbox',{'run':r.name},'name')
from relay_core import whatsapp
with patch.object(whatsapp,'enqueue',return_value={'accepted':1}) as send:
 service.dispatch(out);service.dispatch(out)
 assert send.call_count==1,send.call_count
assert frappe.db.get_value('Relay Automation Outbox',out,'status')=='Submitted'
print('PASS real transaction: ticket + outbox + replay dedup + single dispatch')
m=message();r=process(m,decision(reply='NOT-APPROVED'));assert r.status=='Handoff'
assert not frappe.db.exists('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})
print('PASS invalid model action cannot create ticket or send')
m=message();r=process(m,decision());assert r.status=='Completed'
out=frappe.db.get_value('Relay Automation Outbox',{'run':r.name},'name')
service.takeover(relay_contact.name);frappe.db.commit()
with patch.object(whatsapp,'enqueue') as send:service.dispatch(out);send.assert_not_called()
assert frappe.db.get_value('Relay Automation Outbox',out,'status')=='Cancelled'
print('PASS human takeover cancels queued reply')
service.takeover(relay_contact.name,0);frappe.db.commit()
m=message();r=process(m,decision());assert r.status=='Completed'
out=frappe.db.get_value('Relay Automation Outbox',{'run':r.name},'name')
with patch.object(whatsapp,'enqueue',side_effect=TimeoutError):service.dispatch(out)
assert frappe.db.get_value('Relay Automation Outbox',out,'status')=='Uncertain'
with patch.object(whatsapp,'enqueue') as send:service.dispatch(out);send.assert_not_called()
print('PASS ambiguous send is not blindly replayed')
try:
 frappe.get_doc(dict(doctype='Relay Automation Run',event_key='forged',message=m.name,policy=policy.name,policy_version=str(policy.modified),execution_user=user,flags={'relay_internal':True})).insert()
 raise AssertionError('forged runtime insert was permitted')
except frappe.PermissionError:frappe.db.rollback()
print('PASS document flags cannot bypass runtime service guard')

# Shadow decisions have no ticket/outbox side effects.
policy.reload();policy.mode='Shadow';policy.save();frappe.db.commit()
m=message();r=process(m,decision());assert r.status=='Shadow'
assert not frappe.db.exists('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})
assert not frappe.db.exists('Relay Automation Outbox',{'run':r.name})
print('PASS shadow mode has no action side effects')
policy.reload();policy.mode='Automatic';policy.save();frappe.db.commit()
m=message();r=process(m,decision());assert r.status=='Completed'
out=frappe.db.get_value('Relay Automation Outbox',{'run':r.name},'name')
endpoint=frappe.get_doc('Relay Contact Endpoint',frappe.db.get_value('Relay Contact Endpoint',{'channel':channel.name},'name'))
endpoint.verified=0;endpoint.save();frappe.db.commit()
with patch.object(whatsapp,'enqueue') as send:service.dispatch(out);send.assert_not_called()
assert frappe.db.get_value('Relay Automation Outbox',out,'status')=='Cancelled'
print('PASS revoked endpoint cancels queued delivery')
endpoint.verified=1;endpoint.save();frappe.db.commit()
# Stale policy changes are visible after provider inference, including PostgreSQL snapshots.
m=message()
name=frappe.db.get_value('Relay Automation Run',{'message':m.name},'name')
def change_policy(*args):
 old=frappe.session.user;frappe.set_user('Administrator')
 changed=frappe.get_doc('Relay Automation Policy',policy.name);changed.enabled=0;changed.save();frappe.db.commit();frappe.set_user(old)
 return decision()
with patch.object(service,'complete',side_effect=change_policy),patch.object(frappe,'enqueue'):service.process(name)
assert frappe.db.get_value('Relay Automation Run',name,'status')=='Handoff'
assert not frappe.db.exists('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})
print('PASS policy disabled during inference blocks actions')
policy.reload();policy.enabled=1;policy.save();frappe.db.commit()
# Projection replays, unknown endpoints and status callbacks.
from relay_core.automation import projection
payload={'entry':[{'changes':[{'value':{'messages':[{'id':'synthetic-'+channel.name,'from':'919000000001','type':'text','text':{'body':'Hello'}}]}}]}]}
with patch.object(frappe,'enqueue'):
 event=frappe.get_doc(dict(doctype='Relay Hub Event',event_key='projection-'+channel.name,account='synthetic-account',hub_event_id='1',payload=json.dumps(payload))).insert()
 # Fixture channel account is made unique for deterministic projection.
 channel.account='account-'+channel.name;channel.save();event.account=channel.account
 frappe.db.set_value('Relay Hub Event',event.name,'account',channel.account)
 projection.project(event.name);frappe.db.commit()
 assert frappe.db.get_value('Relay Hub Event',event.name,'projection_status')=='Projected'
 count=frappe.db.count('Relay Message',{'channel':channel.name})
 projection.project(event.name);frappe.db.commit()
 assert frappe.db.count('Relay Message',{'channel':channel.name})==count
print('PASS real projection is replay-safe')
service.takeover(relay_contact.name,0);frappe.db.commit()
# Configured provider fallback uses the same policy scope and per-attempt budget.
from relay_core.automation.providers import ProviderError
frappe.set_user('Administrator')
fallback=frappe.get_doc(dict(doctype='Relay AI Provider',provider='OpenAI',model='fixture-model',api_key='not-a-real-key',enabled=1)).insert()
policy.reload();policy.fallback_provider=fallback.name;policy.save();frappe.db.commit()
with patch.object(service,'complete',side_effect=[ProviderError('synthetic outage'),decision()]) as infer:
 assert service.complete_with_fallback(policy,'Synthetic JSON prompt')==decision()
 assert [call.args[0] for call in infer.call_args_list]==['OpenRouter','OpenAI']
with patch.object(service,'complete',side_effect=ProviderError('synthetic outage')) as infer:
 try:service.complete_with_fallback(policy,'Synthetic JSON prompt')
 except ProviderError:pass
 else:raise AssertionError('Both failures did not stop inference')
 assert infer.call_count==2
policy.daily_limit=1
with patch.object(service,'complete') as infer:
 try:service.complete_with_fallback(policy,'Synthetic JSON prompt')
 except ValueError:pass
 else:raise AssertionError('Daily limit bypassed')
 infer.assert_not_called()
policy.reload();policy.fallback_provider=None;policy.save();frappe.db.commit()
print('PASS configured fallback is bounded to two providers and cannot bypass daily attempt budget')
m=message()
name=frappe.db.get_value('Relay Automation Run',{'message':m.name},'name')
from concurrent.futures import ThreadPoolExecutor
import time
calls=[]
def model(*args):calls.append(1);time.sleep(0.15);return decision()
def worker():
 frappe.init(site='relay-ai-test.local');frappe.connect();frappe.set_user('Administrator');frappe.conf.relay_automation_enabled=1
 try:service.process(name)
 finally:frappe.destroy()
with patch.object(service,'complete',side_effect=model),patch.object(frappe,'enqueue'):
 with ThreadPoolExecutor(max_workers=2) as executor:list(executor.map(lambda _:worker(),range(2)))
assert len(calls)==1,len(calls)
assert frappe.db.count('Relay Ticket',{'source_action_key':action_key(m.name,'ticket')})==1
print('PASS two concurrent real-DB workers create one ticket and decision')
frappe.destroy()
