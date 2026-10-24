from site_labels import run_label
import os,time,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import cases,teams
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
contact=frappe.db.get_value('Relay Contact',{'display_name':['like','Inbox %']},'name');assert contact
suffix = run_label();created=None
schema={'fields':{'type':'object','properties':{'note':{'type':'string'},'completion_evidence':{'type':'string'}}},'priority':'High','initial_stage':'open','stages':[{'key':'open','label':'Open','state':'open'},{'key':'completed','label':'Completed','state':'done','required_fields':['completion_evidence']}]}
kind=frappe.get_doc({'doctype':'Relay Case Type','type_key':'fixture.'+suffix,'title':'Fixture callback','enabled':1,'definition':json.dumps(schema)}).insert();frappe.db.commit()
def rejected(fn):
 try:fn()
 except (ValueError,frappe.ValidationError,frappe.PermissionError):frappe.db.rollback()
 else:raise AssertionError('Expected rejection')
try:
 assert kind.name in [row['name'] for row in cases.types(contact)]
 created=cases.create_manual(kind.name,contact,'Callback request',{'note':'Tomorrow'},suffix)
 assert cases.create_manual(kind.name,contact,'Callback request',{'note':'Tomorrow'},suffix)['name']==created['name']
 rejected(lambda:cases.create_manual(kind.name,contact,'Changed request',{'note':'Tomorrow'},suffix))
 assert cases.directory(contact)['items'][0]['name']==created['name']
 rejected(lambda:cases.move(created['name'],'completed',{},created['modified']))
 done=cases.move(created['name'],'completed',{'completion_evidence':'Call completed'},created['modified'])
 assert done['state']=='done' and done['closed_at'] and done['priority']=='High'
 rejected(lambda:cases.move(created['name'],'open',{},created['modified']))
 schema['stages'][1]['required_fields']=['note'];kind.definition=json.dumps(schema);kind.save();frappe.db.commit()
 assert cases.read(created['name'])['definition']['stages'][1]['required_fields']==['completion_evidence']
 kind.enabled=0;kind.save();frappe.db.commit()
 assert cases.create_manual(kind.name,contact,'Callback request',{'note':'Tomorrow'},suffix)['name']==created['name']
 rejected(lambda:cases.create(kind.name,contact,'New request',{},suffix+'new'))
 team=teams.save('Case test '+suffix,['relay-agent-a@example.invalid','relay-agent-b@example.invalid']);teams.assign(contact,team['name'],'relay-agent-a@example.invalid');frappe.db.commit()
 assigned=cases.assign(created['name'],'relay-agent-a@example.invalid',done['modified']);done=assigned
 assert assigned['assigned_to']=='relay-agent-a@example.invalid'
 rejected(lambda:cases.assign(created['name'],'relay-agent-b@example.invalid',assigned['modified']))
 assert 'relay-agent-a@example.invalid' in [r['name'] for r in cases.agents(created['name'])]
 assert [r['name'] for r in cases.agents(created['name'],query='relay-agent-a@example.invalid')]==['relay-agent-a@example.invalid']
 assert not cases.agents(created['name'],query='no-such-agent')
 frappe.db.savepoint('crowded_agent_directory')
 stamp=frappe.utils.now_datetime()
 decoys=['aaa-case-'+suffix+'-'+str(i)+'@example.invalid' for i in range(40)]
 frappe.db.bulk_insert('User',fields=['name','email','full_name','enabled','creation','modified'],values=[[u,u,'Unrelated case agent',1,stamp,stamp] for u in decoys])
 frappe.db.bulk_insert('Has Role',fields=['name','parent','parenttype','parentfield','role','creation','modified'],values=[['case-role-'+suffix+'-'+str(i),u,'User','roles','Relay Communication User',stamp,stamp] for i,u in enumerate(decoys)])
 assert 'relay-agent-a@example.invalid' not in [r['name'] for r in teams.agents()]
 scoped=cases.agents(created['name'])
 assert 'relay-agent-a@example.invalid' in [r['name'] for r in scoped]
 assert not set(decoys).intersection(r['name'] for r in scoped)
 assert not cases.agents(created['name'],query='%')
 assert len(teams.agents())==30
 frappe.db.rollback(save_point='crowded_agent_directory')
 print('PASS case agent search filters assignment before the 30-result bound, excludes 40 unrelated users and treats wildcards literally')
 assert len(teams.agents())<=30
 rejected(lambda:teams.agents(query='x'*81))
 frappe.set_user('relay-agent-a@example.invalid');rejected(lambda:cases.assign(created['name'],'',assigned['modified']));assert cases.read(created['name'])['state']=='done'
 assert created['name'] in [row.name for row in cases.workspace(query='Callback request')['items']]
 reopened=cases.move(created['name'],'open',{},done['modified']);assert reopened['closed_at'] is None
 frappe.set_user('relay-agent-b@example.invalid');assert created['name'] not in [row.name for row in cases.workspace(query='Callback request')['items']];rejected(lambda:cases.directory(contact));rejected(lambda:cases.move(created['name'],'completed',{'completion_evidence':'No access'},reopened['modified']))
 frappe.set_user('Guest');rejected(lambda:cases.read(created['name']))
 print('PASS case creation/replay, evidence enforcement, closed time, stale edits, pinned lifecycle and guest denial')
finally:
 frappe.set_user('Administrator')
 if created:frappe.delete_doc('Relay Case',created['name'],ignore_permissions=True)
 frappe.delete_doc('Relay Case Type',kind.name,ignore_permissions=True);frappe.db.commit();frappe.destroy()
