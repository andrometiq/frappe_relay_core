"""Grouped inbox, business association and claim isolation on the synthetic site."""
from site_labels import run_label, phone as fixture_phone
import os,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from relay_core import business_groups,business_inbox,teams
from relay_core.business_access import allowed
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922'
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
stamp = run_label();phone=fixture_phone(stamp);dt='Relay Inbox Simulation Business';user='relay-agent-a@example.invalid'
try:
 config=frappe.get_doc('Relay Contact Type',{'business_doctype':dt});config.grouping_field='title';config.save()
 a=frappe.get_doc({'doctype':dt,'title':'Group A '+stamp}).insert();b=frappe.get_doc({'doctype':dt,'title':'Group B '+stamp}).insert()
 person=frappe.get_doc({'doctype':'Contact','first_name':'Grouped '+stamp,
  'phone_nos':[{'phone':phone,'is_primary_mobile_no':1}],
  'links':[{'link_doctype':dt,'link_name':a.name},{'link_doctype':dt,'link_name':b.name}]}).insert()
 contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Grouped '+stamp}).insert()
 channel=frappe.get_all('Relay Channel',filters={'channel':'WhatsApp'},pluck='name',limit_page_length=1)[0]
 messages=[]
 # Disable unrelated automation enqueue during synthetic setup, not permission evaluation.
 for business in (a,b):
  message=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel,'direction':'Incoming','status':'Delivered','content':'Scoped '+business.name,'business_doctype':dt,'business_name':business.name}).insert();messages.append(message)
 assert [r['name'] for r in business_inbox.messages(dt,a.name)['items']]==[messages[0].name]
 assert [r['name'] for r in business_inbox.messages(dt,b.name)['items']]==[messages[1].name]
 context=business_inbox.context(dt,a.name);assert context['title']==a.title and context['contact_count']==1
 linked=business_inbox.contacts(dt,a.name,query='Grouped')['items']
 assert len(linked)==1 and linked[0]['value']==person.name and linked[0]['label']==person.full_name and linked[0]['has_phone'],repr(linked)
 assert ''.join(character for character in linked[0]['description'] if character.isdigit()).endswith(phone)
 assert business_inbox.contacts(dt,a.name,query=phone[-6:])['items'][0]['value']==person.name
 from relay_core import conversation_start
 with patch.object(conversation_start,'connection_value',return_value=frappe.db.get_value('Relay Channel',channel,'account')):
  choices=conversation_start.business_options(person.name,dt,a.name)
  assert len(choices)==1 and choices[0]['provider']=='WhatsApp' and choices[0]['value']==channel
  relay_name,endpoint_name=conversation_start.ensure_business_binding(person.name,channel,dt,a.name)
  assert relay_name==contact.name and frappe.db.get_value('Relay Contact Endpoint',endpoint_name,'verified')
 from relay_core import summaries
 summary_rows,truncated=summaries.source_rows(None,channel,'all',dt,a.name)
 assert [row['message'] for row in summary_rows]==[messages[0].name] and not truncated
 assert summary_rows[0]['contact']==contact.display_name
 ambiguous=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel,'direction':'Incoming','status':'Delivered','content':'Unassigned shared contact'}).insert()
 assert not allowed(ambiguous)
 assert ambiguous.name not in {r['name'] for r in business_inbox.messages(dt,a.name)['items']}
 group=business_groups.directory(dt,query=stamp);assert len(group['items'])==2
 assert len(business_groups.records(dt,group=a.title)['items'])==1
 claim=business_groups.claim(dt,a.title);assert claim['assigned_to']=='Administrator'
 frappe.get_doc({'doctype':'User Permission','user':user,'allow':dt,'for_value':a.name,
  'apply_to_all_doctypes':1}).insert(ignore_permissions=True)
 frappe.clear_cache(user=user)
 frappe.set_user(user)
 try:business_groups.claim(dt,a.title)
 except frappe.ValidationError:pass
 else:raise AssertionError('Claim stolen')
 frappe.set_user('Administrator');business_groups.claim(dt,a.title,release=True)
 frappe.set_user(user);business_groups.claim(dt,a.title)
 from relay_core.permissions import assignment_allowed
 assert assignment_allowed(contact.name,user),'Group handler cannot handle its contact'
 assert messages[0].name in {r.name for r in frappe.get_list('Relay Message',filters={'relay_contact':contact.name},fields=['name'])}
 frappe.set_user('Administrator');frappe.clear_cache(user=user);frappe.set_user(user)
 visible={r.name for r in frappe.get_list('Relay Message',filters={'relay_contact':contact.name},fields=['name'])}
 assert messages[0].name in visible and messages[1].name not in visible,'Business permission leaked through shared contact'
 assert not frappe.get_doc('Relay Message',messages[1].name).has_permission('read')
 snapshots=business_inbox.messages(dt,a.name,names=[m.name for m in messages])['items']
 assert [r['name'] for r in snapshots]==[messages[0].name], 'Snapshot request crossed business boundary'
 business_inbox.mark_visible(dt,a.name,[messages[0].name],messages[0].name)
 business_inbox.save_view(dt,a.name,messages[0].name,17,0)
 saved=business_inbox.view_state(dt,a.name)
 assert saved['name']==messages[0].name and saved['offset']==17 and saved['last_read']==messages[0].name
 business_inbox.typing(dt,a.name,contact.name,1,messages[0].name)
 frappe.set_user('Administrator')
 viewers=business_inbox.presence(dt,a.name)['users']
 assert any(row['name']==user and row['typing'] for row in viewers),'Business typing state was not visible'
 frappe.set_user(user);business_inbox.typing(dt,a.name,contact.name,0,messages[0].name)
 from relay_core import message_reads
 coverage=message_reads.coverage(messages[0].name)
 assert coverage['expected']==1 and coverage['read']==1 and coverage['read_by'][0]['user']==user
 cursors=message_reads.cursors([messages[0].name])
 assert cursors['readers'][0]['last_read_message']==messages[0].name
 try:business_inbox.messages(dt,a.name,names=[messages[0].name]*51)
 except frappe.ValidationError:pass
 else:raise AssertionError('Unbounded snapshot request accepted')
 try:business_inbox.messages(dt,b.name)
 except frappe.PermissionError:pass
 else:raise AssertionError('Denied business timeline exposed')
 print('PASS business viewport, exact read evidence, cursor bubble and shared-contact permission boundary')
 frappe.set_user('Administrator')
 from relay_core.canned_replies import directory as reply_directory
 published=frappe.get_doc({'doctype':'Relay Canned Reply','title':'Published '+stamp,'channel':'WhatsApp','language':'en','body':'Available reply','published':1}).insert()
 private=frappe.get_doc({'doctype':'Relay Canned Reply','title':'Draft '+stamp,'channel':'WhatsApp','language':'en','body':'Not published','published':0}).insert()
 assert {published.name,private.name}<={r.name for r in reply_directory(query=stamp)['items']}
 frappe.set_user(user)
 replies=reply_directory(query=stamp)
 assert {r.name for r in replies['items']}=={published.name} and not replies['can_configure']
 print('PASS communication user reads published canned replies without exposure of drafts')
 frappe.set_user('Administrator')
 provider=frappe.get_doc({'doctype':'Relay AI Provider','provider':'OpenAI','model':'fixture','api_key':'synthetic-not-a-secret','enabled':1}).insert()
 from relay_core.flows.authoring import draft
 with patch('relay_core.automation.providers.complete',return_value={'title':'Support','command':'/support','nodes':[{'id':'done','kind':'handoff','text':'An agent will help.'}]}):
  generated=draft('Collect the request then hand off to an agent.',provider.name)
  assert generated['enabled']==0 and generated['nodes'][0]['kind']=='handoff'
 with patch('relay_core.automation.providers.complete',return_value={'title':'Unsafe','command':'/unsafe','nodes':[{'id':'run','kind':'action','action':'arbitrary.method','arguments':{}}]}):
  try:draft('Execute an arbitrary action.',provider.name)
  except (ValueError,frappe.ValidationError):pass
  else:raise AssertionError('Unknown AI action accepted')
 frappe.set_user(user)
 try:draft('Agent attempts configuration.',provider.name)
 except frappe.PermissionError:pass
 else:raise AssertionError('Agent generated privileged draft')
 print('PASS group responsibility does not require manual contact assignment; AI draft validation and authorisation')
 print('PASS business-specific timelines, ambiguous messages hidden, server grouping, exclusive claim/release')
finally:frappe.db.rollback();frappe.clear_cache(user=user);frappe.destroy()
