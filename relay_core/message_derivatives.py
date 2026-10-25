"""Read derived message text without exposing automation decisions or credentials."""
import json
import frappe
from relay_core.api import validate_reference
from relay_core.permissions import require_access, readable_contact
from relay_core.automation.service import message_hash


@frappe.whitelist(methods=['GET'])
def transcript(message):
    require_access(); validate_reference(message, 'MSG')
    source = frappe.get_doc('Relay Message', message)
    source.check_permission('read'); readable_contact(source.relay_contact)
    frappe.get_doc('Relay Channel', source.channel).check_permission('read')
    if source.message_type not in ('audio', 'voice'):
        return {'available': False, 'status': 'unavailable'}
    if source.transcript:
        details = json.loads(source.transcript_details) if isinstance(source.transcript_details, str) else (source.transcript_details or {})
        return {'available': True, 'text': source.transcript, 'kind': 'transcript', 'translated': False,
                'provenance': {key: details.get(key) for key in ('provider', 'model', 'created_at', 'source_hash')}}
    derived=frappe.get_all('Relay Message Translation',filters={'message':message,'source_hash':message_hash(source)},fields=['result'],order_by='creation desc',limit_page_length=1)
    if derived:
        result=json.loads(derived[0].result) if isinstance(derived[0].result,str) else (derived[0].result or {})
        if result.get('transcript'):
            return {'available':True,'text':result['transcript'],'kind':'transcript','translated':False,
                'provenance':result.get('transcript_provenance') or {}}
    # An edited/replaced source must never display an earlier media transcript.
    rows = frappe.get_all('Relay Automation Run',
        filters={'message': message, 'message_hash': message_hash(source)},
        fields=['transcript', 'transcript_metadata', 'status'],
        order_by='creation desc', limit_page_length=10)
    for row in rows:
        if not row.transcript:
            continue
        metadata = json.loads(row.transcript_metadata) if isinstance(row.transcript_metadata, str) else (row.transcript_metadata or {})
        return {'available': True, 'text': row.transcript,
                'kind': 'transcript', 'translated': False,
                'provenance': {key: metadata.get(key) for key in ('provider', 'model', 'created_at', 'source_hash')}}
    pending = source.transcript_status == 'Pending' or any(row.status in ('Pending', 'Deciding') for row in rows)
    return {'available': False, 'status': 'pending' if pending else (source.transcript_status or 'unavailable').lower()}


@frappe.whitelist(methods=['GET'])
def translation(message):
    require_access(); validate_reference(message,'MSG')
    source=frappe.get_doc('Relay Message',message);source.check_permission('read')
    readable_contact(source.relay_contact);frappe.get_doc('Relay Channel',source.channel).check_permission('read')
    rows=frappe.get_all('Relay Message Translation',filters={'message':message,'source_hash':message_hash(source)},
        fields=['status','result'],order_by='creation desc',limit_page_length=1)
    if not rows:return {'available':False,'status':'unavailable'}
    row=rows[0]
    if row.status!='Completed':return {'available':False,'status':row.status.lower()}
    result=json.loads(row.result) if isinstance(row.result,str) else (row.result or {})
    return {'available':bool(result.get('text')),'status':'completed','language':result.get('language'),
        'text':result.get('text',''),'target_language':'en',
        'provenance':{key:result.get(key) for key in ('provider','model','created_at','source_hash','segments')}}
