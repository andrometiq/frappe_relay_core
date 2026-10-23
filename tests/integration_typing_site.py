"""Typing routing and coalescing against the isolated Frappe database/Redis."""
import os,json,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from relay_core import inbox,messaging,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
try:
 stamp=str(time.time_ns());business=frappe.get_doc({'doctype':'Relay Inbox Simulation Business','title':'Typing '+stamp}).insert()
 person=frappe.get_doc({'doctype':'Contact','first_name':'Typing '+stamp,'links':[{'link_doctype':business.doctype,'link_name':business.name}]}).insert()
 contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Typing fixture'}).insert()
 channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Telegram','account':'typing-'+stamp,'enabled':1}).insert()
 endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'123456','verified':1}).insert()
 source=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'sender_endpoint':'123456','direction':'Incoming','status':'Sent','content':'Typing fixture','provider_context':json.dumps({'provider':'Telegram','chat_id':123456})}).insert();frappe.db.commit()
 with patch.object(messaging,'connection_value',return_value=channel.account),patch.object(whatsapp,'client') as client:
  inbox.typing(contact.name,message=source.name);inbox.typing(contact.name,message=source.name)
  client.return_value.call_tool.assert_called_once_with('telegram.typing',{'chat_id':123456,'message_thread_id':0})
  inbox.typing(contact.name,active=0,message=source.name)
  assert client.return_value.call_tool.call_count==1
  source.provider_context=json.dumps({'provider':'Telegram','chat_id':123456,'message_thread_id':42});source.save();frappe.db.commit()
  inbox.typing(contact.name,message=source.name)
  assert client.return_value.call_tool.call_args.args[1]['message_thread_id']==42
  assert client.return_value.call_tool.call_count==2
  endpoint.verified=0;endpoint.save();frappe.db.commit()
  try:inbox.typing(contact.name,message=source.name)
  except frappe.PermissionError:pass
  else:raise AssertionError('Revoked endpoint sent a typing signal')
  assert client.return_value.call_tool.call_count==2
 print('PASS Telegram typing route/topic, shared Redis coalescing, stop behavior and revoked endpoint denial')
finally:frappe.destroy()
