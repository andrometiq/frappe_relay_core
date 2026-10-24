"""Telegram/email campaign recovery using the guarded database and fake Hub boundary."""
from site_labels import run_label
import os,json,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import campaigns,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator')
frappe.reload_doc('relay_core','doctype','relay_campaign',force=True)
stamp = run_label();account='multi-campaign-'+stamp
business=frappe.get_doc({'doctype':'Relay Inbox Simulation Business','title':'Multi campaign '+stamp}).insert()
person=frappe.get_doc({'doctype':'Contact','first_name':'Multi campaign '+stamp,'links':[{'link_doctype':business.doctype,'link_name':business.name}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Campaign fixture'}).insert()
class Hub:
 def __init__(self):self.receipts={};self.calls=0
 def call_tool(self,tool,args):
  if tool=='channels.deliveries':
   row=self.receipts.get(args['request_key']);return {'deliveries':[row] if row else []}
  assert tool in ('telegram.message','email.send')
  self.calls+=1;key=args['request_key']
  result={'message_id':self.calls+100 if tool=='telegram.message' else '<campaign-'+str(self.calls)+'@example.invalid>','delivery_id':self.calls}
  self.receipts[key]={'id':self.calls,'key':key,'operation':tool,'state':'submitted','result':result}
  raise whatsapp.HubError('Simulated response lost after provider acceptance')
hub=Hub()
try:
 with patch.object(campaigns,'connection_value',return_value=account),patch.object(whatsapp,'client',return_value=hub),patch.object(frappe,'enqueue'):
  for provider,operation,address,args in [('Telegram','telegram.send','123456',{'body':'Telegram campaign'}),('Email','email.send','campaign@example.invalid',{'subject':'Email campaign','body':'Email body'})]:
   channel=frappe.get_doc({'doctype':'Relay Channel','channel':provider,'account':account,'enabled':1}).insert()
   endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':address,'verified':1}).insert();frappe.db.commit()
   assert any(row['channel']==provider for row in campaigns.channels())
   name=campaigns.create(provider+' fixture',channel.name,business.doctype,business.name,operation,args,'campaign-'+stamp+'-'+provider)['name']
   campaigns.add_recipients(name,[person.name]);campaigns.control(name,'start');before=hub.calls
   campaigns.process(name)
   assert campaigns.read(name)['counts']=={'Uncertain':1},campaigns.read(name)
   assert hub.calls==before+1
   campaigns.process(name)
   result=campaigns.read(name);assert result['status']=='Completed' and result['counts']=={'Submitted':1},result
   assert hub.calls==before+1,'Recovery submitted a second message'
   key=frappe.db.get_value('Relay Campaign Recipient',{'campaign':name},'request_key')
   message=frappe.get_doc('Relay Message',frappe.db.get_value('Relay Message',{'source_key':key},'name'))
   assert frappe.parse_json(message.provider_context)['provider']==provider and message.content==args['body']
   campaigns.refresh(name);assert frappe.db.count('Relay Message',{'source_key':key})==1
   cancelled=campaigns.create('Cancel '+provider,channel.name,business.doctype,business.name,operation,args,'cancel-'+stamp+'-'+provider)['name']
   campaigns.add_recipients(cancelled,[person.name]);campaigns.control(cancelled,'cancel');campaigns.process(cancelled)
   assert campaigns.read(cancelled)['status']=='Cancelled' and hub.calls==before+1
   denied=campaigns.create('Revoked '+provider,channel.name,business.doctype,business.name,operation,args,'revoke-'+stamp+'-'+provider)['name']
   campaigns.add_recipients(denied,[person.name]);endpoint.verified=0;endpoint.save();frappe.db.commit()
   campaigns.control(denied,'start');campaigns.process(denied)
   assert campaigns.read(denied)['counts']=={'Rejected':1} and hub.calls==before+1
   print('PASS',provider,'campaign lost-response receipt recovery, history projection/dedup, pending cancellation and revoked endpoint denial')
finally:frappe.destroy()
