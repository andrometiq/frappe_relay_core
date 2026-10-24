"""Guarded database acceptance for internal conversation discussion."""
from site_labels import run_label
from unittest.mock import patch
import os,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import collaboration,teams
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
users=['relay-agent-a@example.invalid','relay-agent-b@example.invalid']
contacts=frappe.get_all('Relay Contact',filters={'display_name':['like','Inbox %']},fields=['name'],order_by='creation desc',limit_page_length=2)
assert len(contacts)==2,'Run inbox integration first'
contact=contacts[0].name;other=contacts[1].name
message=frappe.db.get_value('Relay Message',{'relay_contact':contact},'name');wrong=frappe.db.get_value('Relay Message',{'relay_contact':other},'name')
run = run_label();team=teams.save('Discussion '+run,users);teams.assign(contact,team['name']);frappe.db.commit()
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Permission boundary failed')
try:
 frappe.set_user(users[0]);key='comment-'+run
 with patch('relay_core.realtime.contact_changed') as changed:
  first=collaboration.add(contact,'Synthetic internal handoff',key,[message],assigned_to=users[1],mentions=[users[1]]);frappe.db.commit()
  assert [c.args for c in changed.call_args_list if c.args[1]=='comments']==[(contact,'comments')]
 second=collaboration.add(contact,'Synthetic internal handoff',key,[message],assigned_to=users[1],mentions=[users[1]]);assert second['name']==first['name']
 assert first['messages']==[message]
 assert first['task_status']=='Open' and first['assigned_to']==users[1]
 assert any(row['value']==users[1] for row in collaboration.colleagues(contact))
 frappe.db.savepoint('crowded_colleagues')
 stamp=frappe.utils.now_datetime()
 decoys=['aaa-colleague-'+run+'-'+str(i)+'@example.invalid' for i in range(40)]
 frappe.db.bulk_insert('User',fields=['name','email','full_name','enabled','creation','modified'],values=[[u,u,'Unrelated colleague',1,stamp,stamp] for u in decoys])
 frappe.db.bulk_insert('Has Role',fields=['name','parent','parenttype','parentfield','role','creation','modified'],values=[['colleague-role-'+run+'-'+str(i),u,'User','roles','Relay Communication User',stamp,stamp] for i,u in enumerate(decoys)])
 choices=collaboration.colleagues(contact)
 assert any(row['value']==users[1] for row in choices)
 assert not set(decoys).intersection(row['value'] for row in choices)
 assert len(choices)<=30
 assert [row['value'] for row in collaboration.colleagues(contact,query=users[1])]==[users[1]]
 assert not collaboration.colleagues(contact,query='%')
 frappe.db.rollback(save_point='crowded_colleagues')
 print('PASS colleague search excludes unrelated users before limiting, preserves assigned teammates and literal search')

 assert frappe.db.count('Relay Notification',{'comment':first['name'],'user':users[1]})==1
 denied(lambda:collaboration.add(contact,'Wrong source','wrong-source-'+run,[wrong]))
 frappe.set_user(users[1]);assert any(row['name']==first['name'] for row in collaboration.comments(contact)['items'])
 denied(lambda:collaboration.edit(first['name'],'Unauthorized edit'))
 alerts=collaboration.notifications()['items'];alert=next(row for row in alerts if row['comment']==first['name'])
 assert alert['kind']=='Task' and not alert['is_read']
 assert collaboration.mark_notification(alert['name'])['read']
 completed=collaboration.task_status(first['name'],'Done');assert completed['task_status']=='Done'
 frappe.db.commit()
 reply=collaboration.add(contact,'Synthetic reply','reply-'+run,reply_to=first['name']);frappe.db.commit();assert reply['reply_to']==first['name']
 frappe.set_user(users[0]);denied(lambda:collaboration.mark_notification(alert['name']));edited=collaboration.edit(first['name'],'Updated handoff');frappe.db.commit();assert edited['body']=='Updated handoff'
 removed=collaboration.edit(first['name'],remove=1);frappe.db.commit();assert removed['deleted'] and not removed['body'] and not removed['messages']
 frappe.set_user('Administrator');teams.assign(contact,team['name'],users[0]);frappe.db.commit()
 frappe.set_user(users[0]);assert not any(row['value']==users[1] for row in collaboration.colleagues(contact))
 frappe.set_user(users[1]);denied(lambda:collaboration.colleagues(contact));denied(lambda:collaboration.comments(contact));denied(lambda:collaboration.edit(reply['name'],'Revoked author'))
 assert not any(row['relay_contact']==contact for row in collaboration.notifications()['items'])
 denied(lambda:collaboration.task_status(first['name'],'Open'))
 print('PASS discussion create/reply/edit/remove, retry deduplication, cross-contact references, authorship, tasks, mentions, notification isolation and revocation checks')
finally:frappe.destroy()
