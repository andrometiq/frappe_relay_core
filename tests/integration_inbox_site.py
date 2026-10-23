"""Real assignment isolation and per-user state in the guarded synthetic site."""
import os
from pathlib import Path
import time
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from frappe.permissions import add_permission
from relay_core import api, teams, inbox, email, tickets, business_inbox, message_reads
from relay_core.permissions import readable_contact, require_business_assignment
frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
frappe.reload_doc('relay_core','doctype','relay_conversation_state',force=True)
run=str(time.time_ns());users=[f'relay-inbox-agent-a-{run}@example.invalid',f'relay-inbox-agent-b-{run}@example.invalid']
for user in users:
 if not frappe.db.exists('User',user):frappe.get_doc({'doctype':'User','email':user,'first_name':'Synthetic agent','send_welcome_email':0,'roles':[{'role':'Relay Communication User'}]}).insert()
business_type='Relay Inbox Simulation Business'
if not frappe.db.exists('DocType',business_type):
 frappe.get_doc({'doctype':'DocType','name':business_type,'module':'Relay Core','custom':1,'autoname':'field:title','fields':[{'fieldname':'title','fieldtype':'Data','label':'Title','reqd':1}],'permissions':[{'role':'System Manager','read':1,'write':1,'create':1},{'role':'Relay Communication User','read':1}]}).insert()
add_permission('Contact','Relay Communication User',0)
add_permission(business_type,'Relay Communication User',0)
contact_type=frappe.db.get_value('Relay Contact Type',{'business_doctype':business_type},'name')
if contact_type:
 contact_type=frappe.get_doc('Relay Contact Type',contact_type);contact_type.enabled=1;contact_type.save()
else:frappe.get_doc({'doctype':'Relay Contact Type','business_doctype':business_type,'enabled':1}).insert()
business=frappe.get_doc({'doctype':business_type,'title':'Inbox '+run}).insert()
person=frappe.get_doc({'doctype':'Contact','first_name':'Inbox '+run,'email_ids':[{'email_id':'inbox-'+run+'@example.invalid','is_primary':1}],'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Inbox '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Email','account':'inbox-'+run,'enabled':1}).insert()
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':person.email_id,'verified':1}).insert()
messages=[]
for i in range(3):messages.append(frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'direction':'Incoming','content':'Synthetic '+str(i),'status':'Sent'}).insert())
team=teams.save('Inbox team '+run,users)
second_person=frappe.get_doc({'doctype':'Contact','first_name':'Second '+run,'links':[{'link_doctype':business_type,'link_name':business.name}]}).insert()
second_contact=frappe.get_doc({'doctype':'Relay Contact','contact':second_person.name,'display_name':'Second '+run}).insert()
second_message=frappe.get_doc({'doctype':'Relay Message','relay_contact':second_contact.name,'channel':channel.name,'direction':'Incoming','content':'Second contact evidence','status':'Sent'}).insert()
teams.assign(second_contact.name,team['name'],users[0])
frappe.db.commit();frappe.clear_cache()
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Unauthorized operation succeeded')
try:
 frappe.set_user(users[0]);denied(lambda:readable_contact(contact.name));assert not api.contacts(query='Inbox '+run)['items']
 print('PASS unassigned conversation hidden from agent and direct reads')
 frappe.set_user('Administrator');teams.assign(contact.name,team['name']);frappe.db.commit()
 for user in users:
  frappe.set_user(user);readable_contact(contact.name);assert api.contacts(query='Inbox '+run)['items'];assert len(api.messages(contact.name)['items'])==3
 assert any(row['value']==team['name'] for row in teams.filter_options(query=run))
 assert any(row['name']==contact.name for row in inbox.directory(team=team['name'])['items'])
 print('PASS team assignment grants both team members permission-filtered reads and team filters')
 frappe.db.savepoint('large_unread_fixture')
 stamp=frappe.utils.now_datetime()
 frappe.db.bulk_insert('Relay Message',fields=['name','owner','creation','modified','modified_by','docstatus','idx','relay_contact','channel','direction','content','status'],
  values=[['RELAY-MSG-'+str(9100000000+i),'Administrator',stamp,stamp,'Administrator',0,0,contact.name,channel.name,'Incoming','Unread scale fixture','Sent'] for i in range(1500)])
 assert inbox.read(contact.name)['unread']==1503
 assert api.conversation_channels(contact.name)['items'][0]['unread']==1503
 frappe.db.rollback(save_point='large_unread_fixture')
 print('PASS exact 1503-message unread count without loading messages into application memory')
 assert api.conversation_channels(contact.name)['items']==[{'value':channel.name,'label':'Email','unread':3,'translation_enabled':False}]
 inbox.save_view(contact.name,messages[2].name,channel=channel.name,offset=12,at_bottom=1)
 inbox.save_view(contact.name,messages[0].name,channel=channel.name,offset=-7,at_bottom=0)
 assert inbox.view_state(contact.name,channel.name)['name']==messages[0].name
 assert inbox.view_state(contact.name,channel.name)['offset']==-7
 assert not inbox.view_state(contact.name,'')
 assert inbox.view_state(contact.name)['channel']==channel.name
 frappe.set_user(users[0]);assert not inbox.view_state(contact.name,channel.name)
 denied(lambda:inbox.save_view(contact.name,second_message.name,channel=channel.name))
 assert inbox.read(contact.name)['unread']==3
 print('PASS channel metadata, independently persisted backward resume positions, user isolation and no false reads')
 frappe.set_user('Administrator');frappe.db.savepoint('business_whatsapp_fixture')
 whatsapp_channel=frappe.get_doc({'doctype':'Relay Channel','channel':'WhatsApp','account':'inbox-whatsapp-'+run,'enabled':1}).insert()
 whatsapp_messages=[frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':whatsapp_channel.name,
  'direction':'Incoming','content':'WhatsApp business '+str(i),'status':'Delivered'}).insert() for i in range(3)]
 whatsapp_second=frappe.get_doc({'doctype':'Relay Message','relay_contact':second_contact.name,'channel':whatsapp_channel.name,
  'direction':'Incoming','content':'WhatsApp second contact','status':'Delivered'}).insert()
 frappe.set_user(users[0]);combined=business_inbox.messages(business_type,business.name)
 assert len(combined['items'])==4 and len({row['relay_contact'] for row in combined['items']})==2
 newest=business_inbox.messages(business_type,business.name,limit=2)
 older=business_inbox.messages(business_type,business.name,before=newest['first'],limit=2)
 assert newest['has_more'] and len(older['items'])==2 and not older['has_more']
 assert not {row['name'] for row in newest['items']}.intersection(row['name'] for row in older['items'])
 assert any(row['name']==business.name for row in business_inbox.records(business_type,query=run)['items'])
 frappe.set_user(users[1]);assert len(business_inbox.messages(business_type,business.name)['items'])==3
 print('PASS business inbox combines Contacts, keyset pages without duplicates and filters other assignments')
 frappe.set_user('Administrator');frappe.db.rollback(save_point='business_whatsapp_fixture')
 frappe.set_user(users[0]);state=inbox.update(contact.name,last_read=messages[1].name,starred=1,folder='Follow up');assert state['unread']==1 and state['starred']==1
 state=inbox.update(contact.name,last_read=messages[0].name);assert state['last_read']==messages[1].name
 assert any(row['name']==contact.name for row in inbox.directory(starred=1,folder='Follow up')['items'])
 assert not inbox.directory(starred=1,folder='Other')['items']
 assert any(row['name']==contact.name for row in inbox.directory(query='Ibx '+run,starred=1)['items'])
 assert not inbox.directory(query='%',starred=1)['items']
 frappe.set_user(users[1]);assert not inbox.directory(starred=1,folder='Follow up')['items'];state=inbox.read(contact.name);assert state['unread']==3 and not state.get('starred')
 frappe.set_user(users[0]);inbox.typing(contact.name)
 frappe.set_user(users[1]);assert any(row['name']==users[0] and row['typing'] for row in inbox.presence(contact.name)['users'])
 frappe.set_user(users[0]);inbox.typing(contact.name,0)
 frappe.set_user(users[1]);assert not any(row['typing'] for row in inbox.presence(contact.name)['users'])
 frappe.set_user(users[0])
 with patch('relay_core.realtime.contact_changed') as notified:
  message_reads.mark(contact.name,[messages[1].name]);message_reads.mark(contact.name,[messages[1].name])
  notified.assert_called_once_with(contact.name,'reads')
 assert frappe.db.count('Relay Message Read',{'message':messages[1].name,'user':users[0]})==1
 assert message_reads.coverage(messages[0].name)['read']==0
 coverage=message_reads.coverage(messages[1].name);assert coverage['read']==1 and coverage['expected']==2 and not coverage['complete']
 denied(lambda:message_reads.mark(contact.name,[second_message.name]))
 frappe.set_user(users[1]);message_reads.mark(contact.name,[messages[1].name]);assert message_reads.coverage(messages[1].name)['complete']
 assert inbox.update(contact.name,last_read=messages[2].name)['unread']==2
 assert next(row for row in inbox.directory(query='Inbox '+run,mode='unread')['items'] if row['name']==contact.name)['unread']==2
 markers=message_reads.cursors([row.name for row in messages])['readers']
 assert {(r['user'],r['last_read_message']) for r in markers}=={(users[0],messages[1].name),(users[1],messages[2].name)}
 assert all('user_image' in r and r['full_name'] for r in markers)
 assert len(message_reads.cursors([messages[1].name])['readers'])==1
 assert not message_reads.cursors([])['readers']
 assert all('user_image' in r for r in message_reads.coverage(messages[1].name)['read_by'])
 print('PASS exact reads and one latest cursor per operator with bounded window and avatar profiles')
 print('PASS read cursor monotonic; stars, folders, typing and unread state isolated per user')
 frappe.set_user('Administrator');teams.assign(contact.name,team['name'],users[0]);frappe.db.commit()
 frappe.set_user(users[1]);denied(lambda:readable_contact(contact.name));denied(lambda:require_business_assignment(person.name));assert not api.contacts(query='Inbox '+run)['items']
 denied(lambda:message_reads.mark(contact.name,[messages[0].name]))
 denied(lambda:message_reads.coverage(messages[1].name))
 frappe.set_user(users[0]);assert all(row['user']!=users[1] for row in message_reads.coverage(messages[1].name)['read_by'])
 assert all(row['user']!=users[1] for row in message_reads.cursors([m.name for m in messages])['readers'])
 print('PASS individual assignment revokes other team members including read coverage, cursor bubbles and direct send boundary')
 frappe.set_user(users[0]);denied(lambda:teams.assign(contact.name,team['name'],users[1]))
 print('PASS agent cannot reassign or escalate access')
 created=tickets.create('Inbox ticket '+run,[messages[0].name,messages[2].name],brief='Synthetic linked evidence')
 frappe.db.commit()
 assert tickets.read(created['name'])['messages'][1]['message']==messages[2].name
 assert tickets.update_status(created['name'],'Resolved')['status']=='Resolved'
 assert any(row['name']==created['name'] for row in tickets.directory(query='Inbox ticket '+run)['items'])
 window=api.message_context(messages[1].name)
 assert window['contact']==contact.name and window['anchor']==messages[1].name
 assert [row['name'] for row in window['items']]==[message.name for message in messages]
 frappe.set_user(users[1]);denied(lambda:tickets.read(created['name']));assert not tickets.directory(query='Inbox ticket '+run)['items']
 frappe.set_user(users[0])
 print('PASS ticket creation/status/directory/exact-message navigation and unrelated-agent denial')

 with patch.object(email,'connection_value',return_value=channel.account),patch.object(email.whatsapp,'client') as client:
  email.send([person.email_id],'Synthetic subject','Synthetic body');assert client.return_value.call_tool.call_count==1
  denied(lambda:email.send([person.email_id],'Synthetic subject','Synthetic body',bcc=['unknown@example.invalid']))
  assert client.return_value.call_tool.call_count==1
  frappe.set_user('Administrator');endpoint.verified=0;endpoint.save();frappe.db.commit();frappe.set_user(users[0])
  denied(lambda:email.send([person.email_id],'Synthetic subject','Synthetic body'));assert client.return_value.call_tool.call_count==1
 print('PASS email enforces verified endpoints for To/CC/BCC and rejects revoked bindings before submission')
 frappe.set_user('Administrator')
 for message, stamp in zip(messages, ['2026-01-03 12:00:00','2026-01-02 12:00:00','2026-01-01 12:00:00']):
  frappe.db.set_value('Relay Message',message.name,'sent_at',stamp)
 frappe.db.set_value('Relay Message',messages[1].name,'content','Literal 100%_value evidence')
 frappe.db.commit();frappe.set_user(users[0])
 chronological=api.messages(contact.name,limit=2)
 assert [row.name for row in chronological['items']]==[messages[1].name,messages[0].name]
 older=api.messages(contact.name,before=chronological['first'],limit=2)
 assert [row.name for row in older['items']]==[messages[2].name]
 newer=api.messages(contact.name,after=messages[2].name,limit=2)
 assert [row.name for row in newer['items']]==[messages[1].name,messages[0].name]
 assert [row.name for row in api.messages(contact.name,query='100%_value')['items']]==[messages[1].name]
 assert not api.messages(contact.name,query='100Xvalue')['items']
 denied(lambda:api.messages(contact.name,before=second_message.name))
 frappe.set_user(users[1]);denied(lambda:api.messages(contact.name,query='evidence'))
 print('PASS chronological paging for late-arriving history, literal search and cursor/contact isolation')
 frappe.set_user(users[0])
 snapshots=api.message_snapshots(contact.name,[messages[1].name,second_message.name])['items']
 assert [row.name for row in snapshots]==[messages[1].name]
 assert snapshots[0].content=='Literal 100%_value evidence'
 directory=inbox.directory(query='Inbox '+run,mode='unread')['items']
 entry=next(row for row in directory if row['name']==contact.name)
 assert entry['unread']==1 and entry['latest_preview']=='Synthetic 0'
 assert not inbox.directory(query='Inbox '+run,mode='unassigned')['items']
 frappe.set_user(users[1]);denied(lambda:api.message_snapshots(contact.name,[messages[1].name]))
 print('PASS visible snapshots isolate contact/assignment and unread directory includes chronological preview')
 frappe.set_user('Administrator')
 old_marker=frappe.db.get_value('Relay Contact',contact.name,'last_message')
 unread_before=inbox.read(contact.name)['unread']
 imported=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,
  'direction':'Incoming','content':'Archived historical fixture','sent_at':'2010-01-01 10:00:00',
  'status':'Delivered','legacy_source':'historical-fixture-'+run}).insert()
 assert frappe.db.get_value('Relay Contact',contact.name,'last_message')==old_marker
 assert inbox.read(contact.name)['unread']==unread_before
 ordered=inbox.directory(query=run)['items']
 positions=[row['name'] for row in ordered]
 assert positions.index(second_contact.name)<positions.index(contact.name)
 assert api.messages(contact.name,channel=channel.name)['items'][0].name==imported.name
 print('PASS activity directory ordering and imported history neither bumps activity nor adds unread messages')


finally:frappe.destroy()
