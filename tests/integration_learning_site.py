"""Reviewed instructions are evaluated without side effects and published immutably."""
from site_labels import run_label
import os,time,json
from pathlib import Path
from unittest.mock import patch
import frappe
from relay_core.learning import service as learning
from relay_core.automation import service
sites=Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites);frappe.init(site='relay-ai-test.local');frappe.connect()
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.set_user('Administrator');frappe.flags.mute_emails=True;frappe.conf.relay_automation_enabled=1
run = run_label();actor='automation-test@example.invalid'
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='Telegram',account='learning-'+run,enabled=1)).insert()
provider=frappe.get_doc(dict(doctype='Relay AI Provider',provider='OpenAI',model='fixture',api_key='synthetic-key',enabled=1)).insert()
policy=frappe.get_doc(dict(doctype='Relay Automation Policy',channel=channel.name,provider=provider.name,execution_user=actor,business_doctype='Relay Test Business',enabled=1,mode='Shadow',daily_limit=100)).insert();frappe.db.commit()
decision=dict(category='Support',brief='Review the issue',create_ticket=False,reply=None,handoff=True)
examples=[dict(message='Help example '+str(i),expected=decision) for i in range(3)]
queue=patch.object(frappe,'enqueue');queue.start()
try:
 name=learning.save('Procedure '+run,policy.name,'Ask for relevant details and hand off.',examples)['name'];frappe.db.commit()
 doc=frappe.get_doc('Relay Learned Procedure',name)
 assert not learning.published_instructions(policy)
 try:doc.instructions='Bypass';doc.save(ignore_permissions=True);raise AssertionError('Generic record mutation allowed')
 except frappe.PermissionError:frappe.db.rollback()
 failed=learning.evaluate(name)['name'];frappe.db.commit()
 with patch.object(learning,'complete_with_fallback',return_value=dict(decision,category='Other')):learning.process(failed)
 assert frappe.db.get_value('Relay Procedure Evaluation',failed,'status')=='Failed'
 try:learning.publish(name,failed,'Reviewed the draft carefully');raise AssertionError('Failed evaluation published')
 except ValueError:pass
 check=learning.evaluate(name)['name'];frappe.db.commit()
 before=frappe.db.count('Relay Automation Outbox')
 with patch.object(learning,'complete_with_fallback',return_value=decision) as model:
  learning.process(check);learning.process(check);assert model.call_count==3
 assert frappe.db.count('Relay Automation Outbox')==before
 assert frappe.db.get_value('Relay Procedure Evaluation',check,'status')=='Passed'
 published=learning.publish(name,check,'Reviewed all three examples and scope');frappe.db.commit();policy.reload()
 assert learning.published_instructions(policy)=='Ask for relevant details and hand off.'
 assert frappe.get_doc('Relay Procedure Version',published['version']).reviewer=='Administrator'
 learning.save('Procedure '+run,policy.name,'A changed unpublished draft.',examples,name=name);frappe.db.commit()
 assert learning.published_instructions(policy)=='Ask for relevant details and hand off.'
 try:learning.publish(name,check,'Reviewed the changed draft');raise AssertionError('Stale evaluation published')
 except ValueError:pass
 policy.instructions='Changed action guidance';policy.save();frappe.db.commit()
 try:learning.published_instructions(policy);raise AssertionError('Changed policy reused untested procedure')
 except ValueError:pass
 frappe.set_user(actor)
 try:learning.directory();raise AssertionError('Execution agent can review/publish learning')
 except frappe.PermissionError:pass
 print('PASS draft isolation, failed/stale evaluation denial, evaluation replay, zero action dispatch, immutable reviewed publication and policy invalidation')
finally:
 queue.stop();frappe.db.rollback();frappe.destroy()
