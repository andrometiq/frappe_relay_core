"""Meta Flow account and role boundary with a fixture Hub; no provider requests."""
import os
from pathlib import Path
from unittest.mock import Mock,patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import meta_flows
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
try:
 hub=Mock();hub.execute.return_value={'id':'333','status':'DRAFT'}
 with patch.object(meta_flows,'checked_client',return_value=(hub,{'flows':True})):
  result=meta_flows.execute('create',{'name':'Support','categories':['CUSTOMER_SUPPORT']});assert result['id']=='333'
  assert hub.execute.call_args.args[0]['operation']=='flows.create'
  for operation,args in [('anything',{}),('get',{'account':'other','id':'333'})]:
   count=hub.execute.call_count
   try:meta_flows.execute(operation,args)
   except frappe.ValidationError:pass
   else:raise AssertionError('Unexpected arguments accepted')
   assert hub.execute.call_count==count
  frappe.set_user('relay-agent-a@example.invalid');count=hub.execute.call_count
  try:meta_flows.execute('publish',{'id':'333'})
  except frappe.PermissionError:pass
  else:raise AssertionError('Ordinary agent published a Flow')
  assert hub.execute.call_count==count
 print('PASS manager lifecycle access, argument allowlist and ordinary-agent denial without provider calls')
finally:frappe.db.rollback();frappe.destroy()
