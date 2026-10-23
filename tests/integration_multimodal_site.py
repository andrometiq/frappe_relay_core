"""Real permission/budget/lease checks around synthetic private image/voice inputs."""
import os,time,json,io,wave
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import frappe
from relay_core.automation import service,multimodal
from relay_core import attachments,messaging,message_derivatives
sites=Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites);frappe.init(site='relay-ai-test.local');frappe.connect()
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.set_user('Administrator');frappe.reload_doc('relay_core','doctype','relay_automation_run',force=True);frappe.flags.mute_emails=True;frappe.conf.relay_automation_enabled=1
run=str(time.time_ns());actor='automation-test@example.invalid'
if not frappe.db.exists('Relay Contact Type',{'business_doctype':'Relay Test Business'}):
 frappe.get_doc({'doctype':'Relay Contact Type','business_doctype':'Relay Test Business','enabled':1}).insert()
person=frappe.get_doc({'doctype':'Contact','first_name':'Multimodal '+run,'links':[{'link_doctype':'Relay Test Business','link_name':'Synthetic Customer'}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Multimodal '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Telegram','account':'media-'+run,'enabled':1}).insert()
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'123456789','verified':1}).insert()
provider=frappe.get_doc({'doctype':'Relay AI Provider','provider':'OpenAI','model':'fixture-model','api_key':'synthetic-key','enabled':1}).insert()
voice_provider=frappe.get_doc({'doctype':'Relay AI Provider','provider':'OpenAI','model':'fixture-transcribe','api_key':'synthetic-key','enabled':1}).insert()
policy=frappe.get_doc({'doctype':'Relay Automation Policy','channel':channel.name,'provider':provider.name,'execution_user':actor,
 'business_doctype':'Relay Test Business','enabled':1,'mode':'Shadow','daily_limit':100,'allow_images':1,'allow_voice':1,'transcription_provider':voice_provider.name}).insert()
frappe.db.commit()
queue=patch.object(frappe,'enqueue');queue.start()
decision={'category':'Query','brief':'Review source media','create_ticket':False,'reply':None,'handoff':True}
image=io.BytesIO();Image.new('RGB',(20,20)).save(image,format='PNG')
voice=io.BytesIO()
with wave.open(voice,'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(8000);output.writeframes(b'\0\0'*8000)

def incoming(kind):
 context={'provider':'Telegram','chat_type':'private','chat_id':123456789,'message_id':int(time.time())%1000000+1,'message_type':kind}
 doc=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'direction':'Incoming','sender_endpoint':'123456789',
  'status':'Sent','message_type':kind,'content':'Source caption','provider_context':json.dumps(context),'message_data':json.dumps({'kind':kind,'media':{'file_id':'fixture-id'}})}).insert()
 frappe.db.commit();return doc,frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
try:
 with patch.object(messaging,'connection_value',return_value=channel.account):
  source,name=incoming('photo')
  with patch.object(attachments,'read',return_value=attachments.response(image.getvalue(),'image/png','source.png',0)),patch.object(service,'complete',return_value=decision) as complete:
   service.process(name)
   assert complete.call_args.kwargs['images'][0]['data']==image.getvalue()
  assert frappe.db.get_value('Relay Automation Run',name,'status')=='Shadow'
  source,name=incoming('voice')
  with patch.object(attachments,'read',return_value=attachments.response(voice.getvalue(),'audio/wav','source.wav',0)),patch.object(multimodal,'transcribe',return_value='Please help with my account') as transcribe,patch.object(service,'complete',return_value=decision) as complete:
   service.process(name);service.process(name)
   assert transcribe.call_count==1 and 'Please help with my account' in complete.call_args.args[3]
  stored=frappe.get_doc('Relay Automation Run',name);assert stored.status=='Shadow' and stored.transcript=='Please help with my account'
  frappe.set_user(actor)
  assert service.runs(query=stored.name)['items'][0]['transcript']==stored.transcript
  visible=message_derivatives.transcript(source.name)
  assert visible['available'] and visible['text']==stored.transcript and visible['translated'] is False
  assert visible['provenance']['model']=='fixture-transcribe'
  assert visible['provenance']['source_hash']==service.message_hash(source)
  assert not any(key in visible for key in ('decision','reason','api_key','policy'))
  old_content=source.content
  frappe.db.set_value('Relay Message',source.name,'content','Changed source')
  assert not message_derivatives.transcript(source.name)['available']
  frappe.db.set_value('Relay Message',source.name,'content',old_content)
  print('PASS source-authorized transcript view, recorded provenance and stale-source rejection')
  direct=frappe.get_doc('Relay Automation Run',stored.name);direct.apply_fieldlevel_read_permissions()
  assert not direct.get('transcript')
  frappe.set_user('Administrator')
  other='media-outsider-'+run+'@example.invalid'
  frappe.get_doc({'doctype':'User','email':other,'first_name':'Media outsider','send_welcome_email':0,'roles':[{'role':'Relay Communication Manager'}]}).insert()
  excluded=frappe.get_doc({'doctype':'Relay Test Business','title':'Excluded '+run}).insert()
  frappe.get_doc({'doctype':'User Permission','user':other,'allow':'Relay Test Business','for_value':excluded.name,'apply_to_all_doctypes':1}).insert()
  frappe.db.commit();frappe.clear_cache(user=other);frappe.set_user(other)
  assert not service.runs(query=stored.name)['items']
  try:message_derivatives.transcript(source.name);raise AssertionError('Transcript leaked outside business permissions')
  except frappe.PermissionError:pass
  frappe.set_user('Administrator')
  print('PASS scoped image inference, voice transcript persistence, shared budget and terminal replay')
  policy.allow_images=0;policy.save();frappe.db.commit();source,name=incoming('photo')
  with patch.object(attachments,'read') as download,patch.object(service,'complete') as complete:
   service.process(name);download.assert_not_called();complete.assert_not_called()
  assert frappe.db.get_value('Relay Automation Run',name,'status')=='Handoff'
  source,name=incoming('voice');frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',0);frappe.db.commit()
  with patch.object(attachments,'read') as download,patch.object(multimodal,'transcribe') as transcribe:
   service.process(name);download.assert_not_called();transcribe.assert_not_called()
  print('PASS disabled modality and revoked source block media access before inference')
  frappe.db.set_value('Relay Contact Endpoint',endpoint.name,'verified',1);policy.daily_limit=1;policy.save();frappe.db.commit()
  key=frappe.cache().make_key(f'relay-ai-budget:{policy.name}:{frappe.utils.now_datetime().date()}');frappe.cache().delete(key)
  source,name=incoming('voice')
  with patch.object(attachments,'read',return_value=attachments.response(voice.getvalue(),'audio/wav','source.wav',0)),patch.object(multimodal,'transcribe',return_value='Budget test'),patch.object(service,'complete') as complete:
   service.process(name);complete.assert_not_called()
  assert frappe.db.get_value('Relay Automation Run',name,'status')=='Handoff'
  print('PASS transcription consumes the same daily attempt budget as reasoning')
  from relay_core import reports
  from pypdf import PdfReader
  policy.allow_report=1;policy.mode='Automatic';policy.daily_limit=100;policy.save();frappe.db.commit()
  source,name=incoming('text')
  report_decision=dict(decision,create_report=True,handoff=False)
  with patch.object(service,'complete',return_value=report_decision): service.process(name)
  result=frappe.get_doc('Relay Automation Run',name)
  assert result.status=='Completed' and frappe.parse_json(result.report_scope)['name']=='Synthetic Customer'
  frappe.set_user(actor)
  report=reports.preview('Relay Test Business','Synthetic Customer')
  assert 1<=report['count']<=100 and report['limit']==100
  raw=reports.from_run(name).get_data();reader=PdfReader(io.BytesIO(raw))
  assert raw.startswith(b'%PDF') and 'Communication report' in reader.pages[0].extract_text()
  frappe.set_user(other)
  for operation in (lambda:reports.preview('Relay Test Business','Synthetic Customer'),lambda:reports.from_run(name)):
   try:operation();raise AssertionError('Report leaked outside business permissions')
   except frappe.PermissionError:pass
  frappe.set_user('Administrator')
  policy.allow_report=0;policy.save();frappe.db.commit();source,name=incoming('text')
  with patch.object(service,'complete',return_value=report_decision):service.process(name)
  assert frappe.db.get_value('Relay Automation Run',name,'status')=='Handoff'
  print('PASS opted-in AI report, real PDF rendering and business-scoped report denial')

finally:
 queue.stop();frappe.db.rollback();frappe.destroy()
