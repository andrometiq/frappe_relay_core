"""Campaign batching, lost-admission recovery and cancellation on the guarded DB."""
import os,time,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import campaigns,whatsapp
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
run=str(time.time_ns());account='campaign-'+run
business=frappe.get_all('Relay Inbox Simulation Business',pluck='name',limit_page_length=1)[0]
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account=account,enabled=1)).insert()
contacts=[]
for i in range(52):
 person=frappe.get_doc(dict(doctype='Contact',first_name='Campaign '+run+' '+str(i),phone_nos=[dict(phone='919777'+str(i).zfill(6),is_primary_mobile_no=1)],links=[dict(link_doctype='Relay Inbox Simulation Business',link_name=business)])).insert();contacts.append(person.name)
frappe.db.commit()
class Hub:
 def __init__(self):self.rows={};self.batches=[];self.lose=True;self.fail_before=False
 def call_tool(self,tool,args):
  if tool=='whatsapp.enqueue':
   self.batches.append(len(args['messages']))
   if self.fail_before:self.fail_before=False;raise whatsapp.HubError('Synthetic admission failure')
   result=[]
   for item in args['messages']:
    self.rows.setdefault(item['key'],dict(id=str(len(self.rows)+1),key=item['key'],state='queued'))
    result.append(dict(self.rows[item['key']]))
   if self.lose:self.lose=False;raise whatsapp.HubError('Synthetic response loss after durable admission')
   return {'deliveries':result}
  if tool=='whatsapp.deliveries':
   if args.get('cancel_id'):
    row=next(row for row in self.rows.values() if row['id']==args['cancel_id'])
    if row['state']!='queued':raise whatsapp.HubError('Not cancellable')
    row['state']='cancelled';return {'cancelled':True}
   row=self.rows.get(args.get('request_key'))
   if not row:raise whatsapp.HubError('Delivery unavailable')
   return {'deliveries':[dict(row)]}
  raise AssertionError(tool)
hub=Hub()
def draft(suffix):return campaigns.create('Fixture '+suffix,channel.name,'Relay Inbox Simulation Business',business,'templates.send',{'name':'fixture_template','language':'en'},'campaign-'+run+'-'+suffix)['name']
try:
 with patch.object(campaigns,'connection_value',return_value=account),patch.object(whatsapp,'checked_client',return_value=(hub,{})),patch.object(frappe,'enqueue'):
  name=draft('cancel');assert draft('cancel')==name
  campaigns.add_recipients(name,contacts[:50]);campaigns.add_recipients(name,contacts[50:]);campaigns.add_recipients(name,[contacts[0]])
  assert campaigns.read(name)['counts']=={'Pending':52}
  campaigns.control(name,'start');campaigns.process(name)
  assert len(hub.rows)==25 and hub.batches==[25]
  assert campaigns.read(name)['counts']['Dispatching']==25
  campaigns.control(name,'pause');campaigns.process(name);assert len(hub.rows)==25
  campaigns.control(name,'cancel')
  for _ in range(4):campaigns.process(name)
  result=campaigns.read(name);assert result['status']=='Cancelled' and result['counts']=={'Cancelled':52},result
  assert len(hub.rows)==25 and all(row['state']=='cancelled' for row in hub.rows.values())
  # A failed request before admission can safely retry its original key.
  second=draft('resume');campaigns.add_recipients(second,[contacts[0]]);campaigns.control(second,'start')
  hub.fail_before=True;campaigns.process(second)
  assert campaigns.read(second)['counts']=={'Dispatching':1}
  campaigns.process(second);assert campaigns.read(second)['counts']=={'Queued':1}
  key=frappe.db.get_value('Relay Campaign Recipient',{'campaign':second},'request_key')
  hub.rows[key].update(state='submitted',result={'messages':[{'id':'wamid.fixture.campaign'}]},delivery_status='sent')
  campaigns.process(second);assert campaigns.read(second)['status']=='Completed'
  assert frappe.db.count('Relay Message',{'source_key':key})==1
  hub.rows[key]['delivery_status']='read';campaigns.refresh(second)
  assert frappe.db.get_value('Relay Message',{'source_key':key},'status')=='Read'
  assert frappe.db.count('Relay Message',{'source_key':key})==1
  # Draft recipient edits are detected before any admission.
  third=draft('changed');campaigns.add_recipients(third,[contacts[1]])
  person=frappe.get_doc('Contact',contacts[1]);person.phone_nos[0].phone='919999999999';person.save();frappe.db.commit()
  before=len(hub.rows);campaigns.control(third,'start');campaigns.process(third)
  assert campaigns.read(third)['counts']=={'Rejected':1} and len(hub.rows)==before
  personalized=draft('personalized')
  entry={'contact':contacts[2],'arguments':{'components':[{'type':'body','parameters':[{'type':'text','text':'Personalized fixture'}]}]}}
  campaigns.add_recipients(personalized,[entry]);campaigns.add_recipients(personalized,[entry])
  assert campaigns.read(personalized)['counts']=={'Pending':1}
  try:campaigns.add_recipients(personalized,[{'contact':contacts[2],'arguments':{'to':'123'}}])
  except frappe.ValidationError:frappe.db.rollback()
  else:raise AssertionError('CSV destination override admitted')
  campaigns.control(personalized,'start');campaigns.process(personalized)
  key=frappe.db.get_value('Relay Campaign Recipient',{'campaign':personalized},'request_key')
  hub.rows[key].update(state='submitted',result={'messages':[{'id':'wamid.personalized.'+run}]})
  campaigns.process(personalized)
  data=frappe.db.get_value('Relay Message',{'source_key':key},'message_data');assert 'Personalized fixture' in json.dumps(data)
  frappe.set_user('relay-agent-a@example.invalid')
  try:campaigns.directory()
  except frappe.PermissionError:pass
  else:raise AssertionError('Agent accessed campaign ledger')
 print('PASS 52-recipient draft/dedup, 25-recipient chunks, response-loss recovery, pause/cancel without sending remaining contacts, stable-key pre-admission retry, completion, personalized content/history, destination-override rejection, changed-recipient rejection and manager boundary')
finally:frappe.destroy()
