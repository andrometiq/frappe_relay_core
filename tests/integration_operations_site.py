"""Real scheduled-job records and role checks; no jobs executed or scheduler enabled."""
import os
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core.operations import recovery_status,JOBS
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
try:
 frappe.conf.pause_scheduler=1
 status=recovery_status();assert status['inactive'] and 'Scheduler is paused' in status['reasons']
 method=next(iter(JOBS));name=frappe.db.get_value('Scheduled Job Type',{'method':method},'name')
 if not name:
  name=frappe.get_doc({'doctype':'Scheduled Job Type','method':method,'frequency':'Cron','cron_format':'* * * * *'}).insert().name
 def first():return next(row for row in recovery_status()['items'] if row['label']==JOBS[method])
 frappe.db.set_value('Scheduled Job Type',name,{'stopped':0,'last_execution':None});assert first()['state']=='Never started'
 frappe.db.set_value('Scheduled Job Type',name,'last_execution','2000-01-01 00:00:00');assert first()['state']=='Overdue'
 frappe.db.set_value('Scheduled Job Type',name,'stopped',1);assert first()['state']=='Stopped'
 frappe.db.set_value('Scheduled Job Type',name,{'stopped':0,'last_execution':frappe.utils.now_datetime()});assert first()['state']=='Recently started'
 log=frappe.get_doc({'doctype':'Scheduled Job Log','scheduled_job_type':name,'status':'Failed'}).insert()
 assert first()['state']=='Failed'
 log.db_set('status','Complete');assert first()['state']=='Completed recently'
 assert len(recovery_status()['items'])==len(JOBS)==9
 frappe.set_user('relay-agent-a@example.invalid')
 try:recovery_status()
 except frappe.PermissionError:pass
 else:raise AssertionError('Operational details disclosed to an ordinary agent')
 print('PASS paused scheduler, never/stopped/overdue/recent job starts, bounded job inventory and manager-only visibility without execution')
finally:frappe.db.rollback();frappe.destroy()
