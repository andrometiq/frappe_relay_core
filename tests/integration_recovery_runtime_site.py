"""Opt-in/maintenance gating and exact scheduler allowlist, without executing recovery."""
import os
from pathlib import Path
from unittest.mock import patch, Mock
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import recovery_runtime as runtime
from relay_core.operations import recovery_status,JOBS
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
try:
 frappe.conf.relay_scoped_recovery_enabled=0
 with patch.object(frappe,'get_all') as query:
  assert runtime.tick()['state']=='disabled';query.assert_not_called()
 frappe.conf.relay_scoped_recovery_enabled=1;frappe.conf.maintenance_mode=1
 with patch.object(frappe,'get_all') as query:
  assert runtime.tick()['state']=='maintenance';query.assert_not_called()
 frappe.conf.maintenance_mode=0;frappe.conf.pause_scheduler=1;frappe.conf.disable_scheduler=1
 rows=[frappe._dict(name='job-'+str(i),method=method,stopped=0) for i,method in enumerate(JOBS)]
 enqueued=[]
 def document(doctype,name):
  assert doctype=='Scheduled Job Type'
  return Mock(enqueue=lambda:enqueued.append(name) or True)
 with patch.object(frappe,'get_all',return_value=rows) as query,patch.object(frappe,'get_doc',side_effect=document):
  result=runtime.tick();assert result['enqueued']==9 and result['state']=='running'
  assert query.call_args.kwargs['filters']=={'method':['in',list(JOBS)]}
 assert set(enqueued)=={row.name for row in rows}
 status=recovery_status();assert not status['inactive'] and status['mode']=='Relay-only recovery'
 rows[0].stopped=1
 with patch.object(frappe,'get_all',return_value=rows[:-1]),patch.object(frappe,'get_doc',side_effect=document):
  result=runtime.tick();assert result['stopped']==1 and result['missing']==1 and result['enqueued']==7 and result['state']=='attention'
 frappe.cache.delete_value(runtime.HEARTBEAT);assert recovery_status()['inactive']
 print('PASS explicit opt-in, maintenance gate, exact9method allowlist, stopped/missing jobs, heartbeat health and missing-heartbeat failure')
finally:
 frappe.cache.delete_value(runtime.HEARTBEAT);frappe.db.rollback();frappe.destroy()
