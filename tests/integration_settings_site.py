"""Encrypted site settings and authorization against the isolated Frappe database."""
import os
from unittest.mock import patch
import frappe
sites=os.environ['RELAY_AUTOMATION_TEST_SITES'];os.chdir(sites)
frappe.init(site='relay-ai-test.local');frappe.connect();assert frappe.conf.db_name=='relay_ai_test_20260922'
frappe.set_user('Administrator')
if not frappe.db.exists('DocType','Relay Settings'):
 frappe.reload_doc('relay_core','doctype','relay_settings',force=True);frappe.db.commit()
from relay_core import settings
secret='synthetic-settings-token-that-is-long-enough'
callback='synthetic-callback-secret-that-is-long-enough'
try:
 with patch.object(settings.HubClient,'call_tool',return_value={'account':'fixture','site':frappe.utils.get_url(),'enabled':True}):
  settings.save_connection('http://127.0.0.1:18081/mcp','fixture',secret,callback)
 assert settings.value('relay_hub_token')==secret
 assert settings.value('relay_callback_secret')==callback
 response=settings.connection();assert secret not in str(response) and callback not in str(response)
 encrypted=frappe.db.sql('select password from "__Auth" where doctype=%s and name=%s and fieldname=%s',('Relay Settings','Relay Settings','hub_token'))[0][0]
 assert encrypted!=secret
 print('PASS settings persist encrypted; reads only expose presence')
 with patch.object(settings.HubClient,'call_tool',return_value={'account':'fixture','site':frappe.utils.get_url(),'enabled':True}):
  settings.save_connection('http://127.0.0.1:18081/mcp','fixture')
 assert settings.value('relay_hub_token')==secret and settings.value('relay_callback_secret')==callback
 print('PASS blank edits preserve credentials')
 with patch.object(settings.HubClient,'call_tool',return_value={'account':'another-account','site':'https://other.site'}):
  try:settings.save_connection('http://127.0.0.1:18081/mcp','fixture',secret)
  except frappe.PermissionError:pass
  else:raise AssertionError('wrong account/site accepted')
 print('PASS mismatched Hub binding rejected')
 from relay_core.automation import settings as ai
 created=ai.save_provider('OpenAI','fixture-model',enabled=0,api_key='synthetic-provider-key')
 assert 'api_key' not in str(ai.providers())
 ai.save_provider('OpenAI','fixture-model-2',name=created['name'])
 assert frappe.get_doc('Relay AI Provider',created['name']).get_password('api_key')=='synthetic-provider-key'
 try:ai.save_provider('Gemini','fixture-model',name=created['name'])
 except frappe.ValidationError:pass
 else:raise AssertionError('Provider change reused another provider credential')
 print('PASS provider settings keep keys write-only, preserve blank edits, require a new key across providers')
 assert any(row['value']==created['name'] for row in ai.references('provider',query='fixture-model-2'))
 assert all(row['value'] not in ('Administrator','Guest') for row in ai.references('execution_user'))
 for kind in ('channel','reply','business_doctype'):
  assert len(ai.references(kind))<=30
 print('PASS bounded policy reference searches and dedicated execution users')
 frappe.set_user('automation-test@example.invalid')
 assert settings.connection()['can_configure'] is False
 try:settings.save_connection('http://127.0.0.1:18081/mcp','fixture',secret)
 except frappe.PermissionError:pass
 else:raise AssertionError('communication manager changed system connection')
 for operation in [ai.providers,lambda:ai.save_provider('OpenAI','fixture-model',api_key='synthetic-key'),ai.policies,lambda:ai.references('provider')]:
  try:operation()
  except frappe.PermissionError:pass
  else:raise AssertionError('Manager changed AI configuration')
 print('PASS communication manager can inspect status but cannot change configuration')
 frappe.set_user('Guest')
 for operation in [settings.connection,lambda:settings.save_connection('http://127.0.0.1:18081/mcp','fixture',secret)]:
  try:operation()
  except frappe.PermissionError:pass
  else:raise AssertionError('guest accepted')
 print('PASS guest cannot read or write connection')
finally:
 frappe.db.rollback();frappe.clear_cache();frappe.destroy()
