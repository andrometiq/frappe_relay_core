import os,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core.flows import retailer,actions
from relay_core import cases
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.clear_cache()
try:
 retailer.install_case_types();frappe.db.commit()
 assert 'retailer.create_follow_up' in actions.definitions()
 run=frappe.get_doc('Relay Flow Run',frappe.get_all('Relay Flow Run',pluck='name',order_by='creation desc',limit_page_length=1)[0])
 for old in frappe.get_all('Relay Case',filters={'source_flow':run.name,'title':'Retailer callback request'},pluck='name'):frappe.delete_doc('Relay Case',old,ignore_permissions=True)
 frappe.db.delete('Relay Flow Action',{'run':run.name,'action':'retailer.create_follow_up'});frappe.db.commit()
 for kind_name in frappe.get_all('Relay Case Type',filters={'type_key':['like','essdee.retailer_connect.%']},pluck='name'):
  kind=frappe.get_doc('Relay Case Type',kind_name);kind.definition=__import__('json').dumps(retailer.case_definition('Normal' if kind.type_key.endswith('.catalogue') else 'High'));kind.save()
 frappe.db.commit()
 node={'kind':'action','action':'retailer.create_follow_up','arguments':{'action_type':'callback','note':'Call tomorrow','field_values':{'party':'Synthetic retailer','colors':['Red','Blue'],'quantity':2}}}
 first=actions.execute(run,node,{},'retailer-fixture-'+run.name)
 node['arguments']['note']='Later information must not overwrite the existing case'
 second=actions.execute(run,node,{},'retailer-fixture-second-step-'+run.name)
 assert first['case']==second['case']
 doc=cases.read(first['case']);assert doc['priority']=='High' and doc['field_values']['party']=='Synthetic retailer'
 assert doc['field_values']['colors']==['Red','Blue'] and doc['field_values']['quantity']==2 and doc['field_values']['note']=='Call tomorrow'
 try:cases.move(doc['name'],'completed',{},doc['modified'])
 except ValueError:frappe.db.rollback()
 else:raise AssertionError('Missing evidence accepted')
 print('PASS real registered retailer adapter, per-run/action-type deduplication, collected fields, priority and required completion evidence')
finally:frappe.destroy()
