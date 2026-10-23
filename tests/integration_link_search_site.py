import os,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
from relay_core.api import business_records
name='Relay Link Search Fixture';mapping=None;doc=None
try:
 if not frappe.db.exists('DocType',name):
  frappe.get_doc({'doctype':'DocType','name':name,'custom':1,'module':'Relay Core','autoname':'hash','title_field':'display_title','show_title_field_in_link':1,'search_fields':'city','fields':[{'fieldname':'display_title','fieldtype':'Data','label':'Title'},{'fieldname':'city','fieldtype':'Data','label':'City'}],'permissions':[{'role':'System Manager','read':1,'create':1,'write':1}]}).insert()
 mapping=frappe.get_doc({'doctype':'Relay Contact Type','business_doctype':name,'enabled':1}).insert()
 doc=frappe.get_doc({'doctype':name,'display_title':'Aster Supplies','city':'Coimbatore'}).insert();frappe.db.commit()
 for query in ['Aster','Coimbatore',doc.name]:
  rows=business_records(name,query);assert len(rows)<=30
  match=next(row for row in rows if row.name==doc.name)
  assert match.label=='Aster Supplies',match
 assert 'Coimbatore' in business_records(name,'Coimbatore')[0].description
 frappe.set_user('relay-agent-a@example.invalid')
 try:business_records(name,'Aster')
 except frappe.PermissionError:pass
 else:raise AssertionError('Restricted business type exposed')
 print('PASS native title/search-field lookup, readable label/description and role boundary')
finally:
 frappe.set_user('Administrator')
 if doc:frappe.delete_doc(name,doc.name,ignore_permissions=True)
 if mapping:frappe.delete_doc('Relay Contact Type',mapping.name,ignore_permissions=True)
 frappe.db.commit();frappe.destroy()
