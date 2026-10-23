"""Independent translation queue with real database/permissions and fixture AI."""
import os,json,time
from pathlib import Path
from unittest.mock import patch
sites=Path(__file__).resolve().parents[1]/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve()
os.chdir(sites)
import frappe
from relay_core import translations,message_derivatives
from relay_core.automation import service
frappe.init(site='relay-ai-test.local');frappe.connect()
assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.set_user('Administrator');frappe.flags.mute_emails=True;frappe.conf.relay_automation_enabled=1
for name in ('relay_automation_policy','relay_automation_run','relay_message_translation'):
 frappe.reload_doc('relay_core','doctype',name,force=True)
frappe.clear_cache();frappe.conf.relay_automation_enabled=1
assert 'relay_core.translations.on_message' in frappe.get_hooks('doc_events')['Relay Message']['after_insert']
run=str(time.time_ns());actor='automation-test@example.invalid'
person=frappe.get_doc({'doctype':'Contact','first_name':'Translation '+run,'links':[{'link_doctype':'Relay Test Business','link_name':'Synthetic Customer'}]}).insert()
contact=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,'display_name':'Translation '+run}).insert()
channel=frappe.get_doc({'doctype':'Relay Channel','channel':'Telegram','account':'translate-'+run,'enabled':1}).insert()
endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel.name,'relay_contact':contact.name,'endpoint':'123456789','verified':1}).insert()
provider=frappe.get_doc({'doctype':'Relay AI Provider','provider':'OpenAI','model':'fixture-model','api_key':'synthetic-key','enabled':1}).insert()
policy=frappe.get_doc({'doctype':'Relay Automation Policy','channel':channel.name,'provider':provider.name,'execution_user':actor,
 'business_doctype':'Relay Test Business','enabled':1,'mode':'Shadow','daily_limit':100,'allow_translation':1,'allow_voice':1,'transcription_provider':provider.name}).insert()
frappe.db.commit()
queue=patch.object(frappe,'enqueue');queue.start()
def incoming(text,kind='text'):
 doc=frappe.get_doc({'doctype':'Relay Message','relay_contact':contact.name,'channel':channel.name,'direction':'Incoming','sender_endpoint':'123456789','status':'Sent','message_type':kind,'content':text,
 'provider_context':json.dumps({'provider':'Telegram','chat_type':'private','chat_id':123456789,'message_id':time.time_ns()%1000000,'message_type':kind}),
 'message_data':json.dumps({'kind':kind,'text':text} if kind=='text' else {'kind':kind,'media':{'file_id':'fixture'}})}).insert()
 frappe.db.commit()
 return doc,frappe.db.get_value('Relay Message Translation',{'message':doc.name},'name')
try:
 long_text=('வணக்கம் '*600).strip()
 with patch.object(translations.providers,'complete',return_value={'language':'ta','text':'Translated section'}) as ai:
  long_result=translations.translate(long_text,policy)
  assert ai.call_count>1 and len(long_result['segments'])==ai.call_count
  assert long_result['segments'][0]['start']==0 and long_result['segments'][-1]['end']==len(long_text)
  assert all(segment['end']-segment['start']<=2000 for segment in long_result['segments'])
 print('PASS long text chunks are bounded and provenance covers every source character')
 first,first_job=incoming('வணக்கம்');second,second_job=incoming('நன்றி')
 assert first_job and second_job
 with patch.object(translations.providers,'complete',return_value={'language':'ta','text':'Hello'}) as ai:
  translations.process(first_job);translations.process(first_job)
  assert ai.call_count==1
 assert frappe.db.get_value('Relay Message Translation',first_job,'status')=='Completed'
 assert frappe.db.get_value('Relay Message',first.name,'content')=='வணக்கம்'
 frappe.set_user(actor);value=message_derivatives.translation(first.name)
 assert value['text']=='Hello' and value['language']=='ta' and value['provenance']['model']=='fixture-model'
 assert value['provenance']['source_hash']==service.message_hash(first)
 frappe.set_user('Administrator')
 print('PASS older burst message translated independently, replay deduplicated, original and provenance retained')
 english,job=incoming('Already English')
 with patch.object(translations.providers,'complete',return_value={'language':'en','text':''}):translations.process(job)
 assert message_derivatives.translation(english.name)['language']=='en' and not message_derivatives.translation(english.name)['available']
 stale,job=incoming('மாற்றம்');frappe.db.set_value('Relay Message',stale.name,'content','Edited source');frappe.db.commit()
 with patch.object(translations.providers,'complete') as ai:translations.process(job);ai.assert_not_called()
 assert not message_derivatives.translation(stale.name)['available']
 print('PASS English stays original and changed-source jobs cannot publish stale translations')
 invalid,job=incoming('Invalid model reply')
 with patch.object(translations.providers,'complete',return_value={'language':'ta','text':'','extra':'bad'}):translations.process(job)
 assert frappe.db.get_value('Relay Message Translation',job,'status')=='Failed'
 print('PASS malformed provider output fails explicitly without changing the message')
 frappe.set_user(actor)
 try:translations.retry(job);raise AssertionError('Non-manager retried translation')
 except frappe.PermissionError:pass
 frappe.set_user('Administrator')
 retried=translations.retry(job);assert retried['name']==job
 with patch.object(translations.providers,'complete',return_value={'language':'en','text':''}):translations.process(job)
 assert frappe.db.get_value('Relay Message Translation',job,'status')=='Completed'
 print('PASS manager-only explicit retry and successful reprocessing')
 voice,job=incoming('Voice source','voice')
 source_run=frappe.get_doc('Relay Automation Run',frappe.db.get_value('Relay Automation Run',{'message':voice.name},'name'))
 source_run.transcript='வணக்கம்';source_run.transcript_metadata=json.dumps({'provider':'Fixture voice','model':'fixture-transcription'})
 service.internal_save(source_run);frappe.db.commit()
 with patch.object(translations.providers,'complete',return_value={'language':'ta','text':'Hello from voice'}):translations.process(job)
 assert message_derivatives.translation(voice.name)['text']=='Hello from voice'
 assert message_derivatives.transcript(voice.name)['text']=='வணக்கம்'
 print('PASS existing voice transcript reused, with original-language transcript and separate English text')
 from relay_core import attachments
 from relay_core.automation import multimodal
 from types import SimpleNamespace
 fresh_voice,fresh_job=incoming('Fresh voice','voice')
 with patch.object(attachments,'read',return_value=SimpleNamespace(get_data=lambda:b'fixture',mimetype='audio/wav')),patch.object(multimodal,'transcribe',return_value='வணக்கம்') as transcribe,patch.object(translations.providers,'complete',return_value={'language':'ta','text':'Shared voice'}):
  translations.process(fresh_job)
  source_run=frappe.get_doc('Relay Automation Run',frappe.db.get_value('Relay Automation Run',{'message':fresh_voice.name},'name'))
  text,_=multimodal.context(policy,fresh_voice,source_run)
  assert text=='வணக்கம்' and transcribe.call_count==1
 print('PASS translation-first voice work is reused by reply inference without another transcription')
 recovery,job=incoming('Recovery fixture')
 frappe.db.set_value('Relay Message Translation',job,{'status':'Processing','attempts':1,'lease_until':frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=60)});frappe.db.commit()
 with patch.object(translations.providers,'complete') as ai:translations.process(job);ai.assert_not_called()
 frappe.db.set_value('Relay Message Translation',job,'lease_until','2000-01-01 00:00:00');frappe.db.commit()
 with patch.object(translations.providers,'complete',return_value={'language':'en','text':''}) as ai:translations.process(job);assert ai.call_count==1
 assert frappe.db.get_value('Relay Message Translation',job,'attempts')==2
 print('PASS live lease exclusion and expired-lease recovery')
 policy.daily_limit=1;policy.save();frappe.db.commit()
 limited,job=incoming('Budget exhausted')
 with patch.object(translations.providers,'complete') as ai:translations.process(job);ai.assert_not_called()
 assert frappe.db.get_value('Relay Message Translation',job,'status')=='Failed'
 print('PASS translation shares and obeys the daily AI budget before provider invocation')
 other='translation-outsider-'+run+'@example.invalid'
 frappe.get_doc({'doctype':'User','email':other,'first_name':'Translation outsider','send_welcome_email':0,'roles':[{'role':'Relay Communication Manager'}]}).insert()
 excluded=frappe.get_doc({'doctype':'Relay Test Business','title':'Translation excluded '+run}).insert()
 frappe.get_doc({'doctype':'User Permission','user':other,'allow':'Relay Test Business','for_value':excluded.name,'apply_to_all_doctypes':1}).insert()
 frappe.db.commit();frappe.clear_cache(user=other);frappe.set_user(other)
 try:message_derivatives.translation(first.name);raise AssertionError('Translation leaked')
 except frappe.PermissionError:pass
 frappe.set_user('Administrator')
 policy.allow_translation=0;policy.save();frappe.db.commit()
 with patch.object(translations.providers,'complete') as ai:translations.process(second_job);ai.assert_not_called()
 _,disabled_job=incoming('Disabled translation');assert disabled_job is None
 print('PASS business isolation, manager opt-out and disabled-policy cancellation before AI calls')
finally:
 queue.stop();frappe.set_user('Administrator');frappe.destroy()
