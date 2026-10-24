"""Overview counts only permitted recent non-archival conversation rows."""
from site_labels import run_label
import os,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import overview,teams
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True;frappe.conf.relay_automation_enabled=0
run = run_label();user='overview-'+run+'@example.invalid'
frappe.get_doc(dict(doctype='User',email=user,first_name='Overview fixture',send_welcome_email=0,roles=[{'role':'Relay Communication User'}])).insert()
business=frappe.get_all('Relay Inbox Simulation Business',pluck='name',limit_page_length=1)[0]
person=frappe.get_doc(dict(doctype='Contact',first_name='Overview '+run,links=[dict(link_doctype='Relay Inbox Simulation Business',link_name=business)])).insert()
contact=frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,display_name='Overview '+run)).insert()
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='Telegram',account='overview-'+run,enabled=1)).insert()
for direction,status,extra in [('Incoming','Delivered',{}),('Outgoing','Failed',{}),('Incoming','Delivered',{'legacy_source':'old-'+run}),('Incoming','Delivered',{'sent_at':'2000-01-01 00:00:00'})]:
 frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=channel.name,direction=direction,status=status,content='Overview fixture',**extra)).insert()
teams.assign(contact.name,assigned_to=user);frappe.db.commit();frappe.clear_cache()
try:
 frappe.set_user(user);result=overview.read()
 assert result['count']==2 and result['directions']=={'Incoming':1,'Outgoing':1} and result['failed_outgoing']==1,result
 assert result['operations'] is None and sum(day['incoming']+day['outgoing'] for day in result['daily'])==2
 frappe.set_user('Administrator');teams.assign(contact.name,assigned_to='relay-agent-a@example.invalid');frappe.db.commit()
 frappe.set_user(user);assert overview.read()['count']==0
 print('PASS overview daily counts, outgoing failures, archival/old-message exclusion, assignment revocation and manager-only operational totals')
finally:frappe.destroy()
