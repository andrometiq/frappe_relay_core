"""Legacy import acceptance on an isolated DB; never writes old installed-site data."""
import json,os,time,tempfile,io,zipfile
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sites=root/'.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve()==sites.resolve();os.chdir(sites)
import frappe
from relay_core import legacy,legacy_bundle,attachments,whatsapp,api
frappe.init(site='relay-ai-test.local');assert frappe.conf.db_name=='relay_ai_test_20260922' and frappe.conf.db_port==18433
frappe.connect();frappe.set_user('Administrator');frappe.flags.mute_emails=True
run=str(time.time_ns())
for kind,content,expected in [
 ('template',{'template':'welcome','template_snapshot':{'header':'Hello','body':'Welcome Sam','footer':'Reply STOP','buttons':[{'text':'View order'}]}},'Hello\n\nWelcome Sam\n\nReply STOP\n\nView order'),
 ('interactive',{'interactive':{'button_reply':{'id':'yes','title':'Yes please'}}},'Yes please'),
 ('interactive',{'interactive':{'call_permission_reply':{'response':'accept'}}},'Call permission: accept')
]:
 row=frappe._dict(message_type=kind,content=content,body='',delivery_status='Read')
 data,quote,url,notes=legacy.converted(row)
 assert data['kind']=='text' and data['text']==expected and not notes,(data,notes)
print('PASS historical template snapshots and interactive replies remain readable')
# Minimal source schemas reproduce the installed legacy fields without invoking its hooks.
for name,fields in {
 'WhatsApp Core Identity':[('normalized_value','Data'),('identifier_type','Data')],
 'WhatsApp Core Conversation':[('channel','Data'),('remote_identity','Data')],
 'WhatsApp Core Message':[(key,'JSON' if key in ('content','failure') else 'Datetime' if key=='provider_timestamp' else 'Long Text' if key=='body' else 'Data') for key in legacy.FIELDS if key not in ('name','owner','creation')]
}.items():
 if not frappe.db.exists('DocType',name):
  frappe.get_doc(dict(doctype='DocType',name=name,module='Relay Core',custom=1,autoname='hash',fields=[dict(fieldname=k,label=k,fieldtype=t) for k,t in fields],permissions=[dict(role='System Manager',read=1,write=1,create=1)])).insert()
frappe.db.commit();frappe.clear_cache()
contact=frappe.db.get_value('Relay Contact',{'display_name':['like','Inbox %']},'name');assert contact,'Run inbox integration first'
channel=frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='archive-'+run,enabled=0)).insert()
identity=frappe.get_doc(dict(doctype='WhatsApp Core Identity',normalized_value='919000099999',identifier_type='Phone')).insert()
conversation=frappe.get_doc(dict(doctype='WhatsApp Core Conversation',channel='legacy-test-'+run,remote_identity=identity.name)).insert()
source=[]
for i in range(52):
 source.append(frappe.get_doc(dict(doctype=legacy.SOURCE,conversation=conversation.name,channel=conversation.channel,
  recipient_address=identity.normalized_value,provider_message_id='legacy-'+run+'-'+str(i),direction='Inbound' if i%2 else 'Outbound',
  message_type='text',body='Legacy fixture '+str(i),content=json.dumps({'context':{'id':'legacy-'+run+'-0'}} if i else {}),
  provider_timestamp='2020-01-01 12:00:00',delivery_status='Received' if i%2 else 'Read')).insert())
from frappe.utils.file_manager import save_file
file=save_file('legacy-evidence.txt',b'Preserved local evidence',legacy.SOURCE,source[0].name,is_private=1)
frappe.db.set_value(legacy.SOURCE,source[0].name,{'message_type':'document','content':json.dumps({'payload':{'local_file_url':file.file_url,'filename':file.file_name}})})
job=frappe.get_doc(dict(doctype='Relay Legacy Import',source_conversation=conversation.name,relay_contact=contact,channel=channel.name)).insert()
frappe.db.commit()
def denied(fn):
 try:fn()
 except frappe.PermissionError:frappe.db.rollback()
 else:raise AssertionError('Unauthorized import accepted')
try:
 before=frappe.db.count('Relay Message',{'channel':channel.name})
 assert legacy.preview(job.name)['messages']==50
 assert frappe.db.count('Relay Message',{'channel':channel.name})==before
 frappe.conf.relay_automation_enabled=1
 with patch.object(whatsapp,'client',side_effect=AssertionError('Import must not call any provider')), patch.object(frappe,'enqueue',side_effect=AssertionError('Import must not enqueue automation')):
  first=legacy.run_batch(job.name);assert first['status']=='Running' and first['imported']==50,first
  second=legacy.run_batch(job.name);assert second['status']=='Completed' and second['imported']==52,second
  assert legacy.run_batch(job.name)['imported']==52
  archived=frappe.db.get_value('Relay Message',{'legacy_source':source[0].name},'name')
  assert attachments.read(archived).get_data()==b'Preserved local evidence'
 assert frappe.db.count('Relay Message',{'channel':channel.name})==52
 assert not frappe.db.exists('Relay Contact Endpoint',{'channel':channel.name})
 assert frappe.db.count(legacy.SOURCE,{'conversation':conversation.name})==52
 history=api.messages(contact,channel=channel.name)
 assert all(str(row.sent_at)=='2020-01-01 12:00:00' for row in history['items'])
 assert any(row.status=='Read' for row in history['items'])
 again=frappe.get_doc(dict(doctype='Relay Legacy Import',source_conversation=conversation.name,relay_contact=contact,channel=channel.name)).insert();frappe.db.commit()
 legacy.run_batch(again.name);result=legacy.run_batch(again.name)
 assert result['imported']==0 and result['skipped']==52,result
 job.reload();job.channel='changed'
 try:job.save()
 except frappe.ValidationError:frappe.db.rollback()
 else:raise AssertionError('Started mapping changed')
 with tempfile.TemporaryDirectory() as directory:
  path=Path(directory)/'history.zip';exported=legacy_bundle.export_conversation(conversation.name,path)
  assert exported['count']==52 and exported['attachments']==1
  bundle=legacy_bundle.decode(path.read_bytes());assert len(bundle['rows'])==52 and len(bundle['files'])==1
  archive_file=save_file('legacy-history.zip',path.read_bytes(),'Relay Legacy Import',None,is_private=1)
  cross_channel=frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='cross-archive-'+run,enabled=0)).insert()
  cross_job=frappe.get_doc(dict(doctype='Relay Legacy Import',source_bundle=archive_file.name,source_conversation=conversation.name,relay_contact=contact,channel=cross_channel.name)).insert();frappe.db.commit()
  assert legacy.preview(cross_job.name)['messages']==50
  with patch.object(whatsapp,'client',side_effect=AssertionError('Bundle import must not call a provider')),patch.object(frappe,'enqueue',side_effect=AssertionError('Bundle import must not enqueue automation')):
   legacy.run_batch(cross_job.name);completed=legacy.run_batch(cross_job.name);assert completed['status']=='Completed' and completed['imported']==52
  copied=frappe.db.get_value('Relay Message',{'channel':cross_channel.name,'provider_id':source[0].provider_message_id},'name')
  assert attachments.read(copied).get_data()==b'Preserved local evidence'
  cross_job.reload();assert cross_job.bundle_sha256==exported['sha256']
  # Contents, not merely the File name, are pinned across resumptions.
  with patch.object(legacy_bundle,'load',return_value={**bundle,'sha256':'changed'}):
   try:legacy.preview(cross_job.name)
   except frappe.ValidationError:frappe.db.rollback()
   else:raise AssertionError('Changed bundle accepted')
  hostile=io.BytesIO()
  with zipfile.ZipFile(hostile,'w') as archive:archive.writestr('../outside','bad')
  try:legacy_bundle.decode(hostile.getvalue())
  except frappe.ValidationError:frappe.db.rollback()
  else:raise AssertionError('Unsafe archive accepted')
 print('PASS cross-site bundle checksum, bounded archive validation, private media, resumable mapping and zero provider/automation calls')
 frappe.set_user('relay-agent-a@example.invalid');denied(lambda:legacy.preview(again.name));denied(lambda:legacy.run_batch(again.name))
 print('PASS preview is read-only; 52-message resumable import, replay deduplication, timestamp/status preservation, private attachment copy, mapping immutability, role denial and zero provider calls')
finally:frappe.destroy()
