"""Bounded invalidations contain no business payload and honor transaction timing."""
import os
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
from relay_core.realtime import changed,contact_changed
try:
 doc=frappe._dict(doctype='Relay Message',name='private-message',relay_contact='private-contact',content='private body')
 with patch.object(frappe,'publish_realtime') as publish:
  changed(doc)
  assert publish.call_count==2
  for call in publish.call_args_list:
   assert call.args==('relay_changed',{'kind':'messages'})
   assert call.kwargs['after_commit'] is True
   assert 'private body' not in repr(call)
  publish.reset_mock();changed(frappe._dict(doctype='User',name='private-user'));assert not publish.called
 with patch('frappe.realtime.emit_via_redis') as transport:
  contact_changed('private-contact','presence')
  assert not transport.called
  frappe.db.rollback();assert not transport.called
  contact_changed('private-contact','presence');frappe.db.commit()
  assert transport.call_count==1
  assert transport.call_args.args==('relay_changed',{'kind':'presence'},'doc:Relay Contact/private-contact')
 print('PASS payload-free scoped invalidation, after-commit publication and rollback suppression')
finally:frappe.destroy()
