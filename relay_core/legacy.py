"""Same-site, resumable legacy history import. Never calls a provider or automation."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.message_updates import provider_key
from relay_core.message_types import normalize
from relay_core.automation.provenance import conversation_key

SOURCE = 'WhatsApp Core Message'
FIELDS = ['name','conversation','channel','recipient_address','provider_message_id','direction',
          'message_type','body','content','provider_timestamp','delivery_status','failure','owner','creation']
MEDIA = {'image','video','audio','document','sticker','template'}


def object_value(value):
    if isinstance(value,str):
        try: value=json.loads(value)
        except (ValueError,TypeError): return {}
    return value if isinstance(value,dict) else {}


def mapping(name):
    require_access(configure=True)
    job=frappe.get_doc('Relay Legacy Import',name);job.check_permission('write')
    readable_contact(job.relay_contact)
    channel=frappe.get_doc('Relay Channel',job.channel);channel.check_permission('read')
    if channel.channel!='WhatsApp':frappe.throw('Legacy WhatsApp history requires a WhatsApp Relay channel')
    if job.get('source_bundle'):
        from relay_core.legacy_bundle import load
        bundle=load(job.source_bundle);manifest=bundle['manifest'];job.flags.legacy_bundle=bundle
        if job.bundle_sha256 and job.bundle_sha256!=bundle['sha256']:frappe.throw('The source bundle changed after import started')
        if job.source_conversation!=manifest['source_conversation']:frappe.throw('Bundle conversation does not match this mapping')
        old=frappe._dict(name=manifest['source_conversation'],channel=manifest['source_channel'])
        endpoint=manifest['endpoint'];kind=manifest.get('identifier_type')
    else:
        if not frappe.db.exists('DocType',SOURCE):frappe.throw('Choose a private export bundle or install the legacy source app on this site')
        old=frappe.get_doc('WhatsApp Core Conversation',job.source_conversation);old.check_permission('read')
        identity=frappe.get_doc('WhatsApp Core Identity',old.remote_identity);identity.check_permission('read')
        endpoint=str(identity.normalized_value or '').strip();kind=identity.identifier_type
    if not endpoint or len(endpoint)>200:frappe.throw('Legacy conversation has no valid remote identity')
    context={'provider':'WhatsApp'}
    if kind=='Group':context['group_id']=endpoint
    return job,old,endpoint,context


def source_rows(job):
    bundle=job.flags.get('legacy_bundle')
    if bundle:return [row for row in bundle['rows'] if (not job.last_source or row.name>job.last_source) and (not job.upper_source or row.name<=job.upper_source)][:51]
    filters={'conversation':job.source_conversation}
    if job.last_source and job.upper_source:filters['name']=['between',[job.last_source,job.upper_source]]
    elif job.upper_source:filters['name']=['<=',job.upper_source]
    # Name is an opaque stable cursor, not a chronological timestamp.
    query=frappe.qb.get_query(SOURCE,fields=FIELDS,filters=filters,order_by='name asc',limit=51,ignore_permissions=False)
    if job.last_source:query=query.where(frappe.qb.DocType(SOURCE).name>job.last_source)
    return query.run(as_dict=True)


def converted(row):
    original=object_value(row.content);kind=str(row.message_type or 'text').lower()
    payload=original.get('payload') or original.get(kind) or {}
    notes=[]
    try:
        data=normalize(kind,payload,provider='WhatsApp',body=row.body or '')
    except (ValueError,TypeError,KeyError):
        data={'kind':'text','text':row.body or '['+kind+' message]'}
        notes.append('Original '+kind+' structure retained for review')
    if kind == 'template':
        snapshot=object_value(original.get('template_snapshot'))
        parts=[snapshot.get(key) for key in ('header','body','footer')]
        buttons=snapshot.get('buttons')
        if isinstance(buttons,list):
            parts += [button.get('text') for button in buttons[:10] if isinstance(button,dict)]
        rendered='\n\n'.join(part for part in parts if isinstance(part,str) and part.strip())
        data={'kind':'text','text':rendered or row.body or '[Template message]'}
        if not rendered:notes.append('Template snapshot unavailable; original parameters retained for review')
        header=str(snapshot.get('header_type') or '').lower()
        if header in ('image','video','document') and snapshot.get('header_media'):
            data={'kind':header,'caption':data['text'],'media':{}}
    elif kind == 'interactive':
        interactive=object_value(payload)
        selected=object_value(interactive.get('button_reply') or interactive.get('list_reply'))
        permission=object_value(interactive.get('call_permission_reply'))
        flow=object_value(interactive.get('nfm_reply'))
        label=selected.get('title') or selected.get('id') or flow.get('body')
        if permission:label='Call permission: '+str(permission.get('response') or 'Response received')
        if label or row.body:data={'kind':'text','text':str(label or row.body)}
    if data['kind']=='unsupported':notes.append('Original '+kind+' structure retained for review')
    if row.delivery_status=='Deleted':data={'kind':'text','text':'[Deleted message]'}
    quote=object_value(original.get('context')).get('id') or object_value(original.get('context')).get('message_id') or original.get('context_message_id')
    if not quote and isinstance(payload,dict):quote=payload.get('context_message_id') or object_value(payload.get('context')).get('id')
    file_url=payload.get('local_file_url') if isinstance(payload,dict) else None
    if kind=='template':file_url=object_value(original.get('template_snapshot')).get('header_media')
    return data,str(quote) if quote else None,file_url,notes


def local_attachment(row,file_url):
    if not isinstance(file_url,str) or not file_url.startswith(('/private/files/','/files/')) or row.message_type not in MEDIA:return None
    # An arbitrary local URL is not enough: the File must belong to this source.
    return frappe.db.get_value('File',{'attached_to_doctype':SOURCE,'attached_to_name':row.name,'file_url':file_url},'name')


@frappe.whitelist(methods=['GET'])
def preview(name):
    job,old,endpoint,context=mapping(name)
    rows=source_rows(job)[:50]
    local=review=0
    for row in rows:
        data,quote,file_url,notes=converted(row)
        bundle=job.flags.get('legacy_bundle')
        attachment=bundle['files'].get(row.name) if bundle else local_attachment(row,file_url)
        local+=bool(attachment)
        review+=bool(notes or row.message_type in MEDIA and not attachment)
    return {'messages':len(rows),'local_attachments':local,'review_required':review,'status':job.status}


def save_job(job):
    previous=getattr(frappe.flags,'relay_legacy_import_write',False)
    frappe.flags.relay_legacy_import_write=True
    try:job.save()
    finally:frappe.flags.relay_legacy_import_write=previous


@frappe.whitelist(methods=['POST'])
def run_batch(name):
    require_access(configure=True)
    with frappe.cache.lock('relay-legacy-import:'+name,timeout=120):
        job,old,endpoint,base_context=mapping(name)
        if job.status=='Completed':return {'status':job.status,'imported':job.imported,'skipped':job.skipped}
        if job.status=='Draft':
            bundle=job.flags.get('legacy_bundle')
            if bundle:
                newest=bundle['rows'][-1:];job.bundle_sha256=bundle['sha256']
                job.warnings='\n'.join(str(note) for note in bundle['manifest'].get('warnings',[])[:500])
            else:newest=frappe.get_list(SOURCE,filters={'conversation':old.name},fields=['name'],order_by='name desc',page_length=1)
            job.upper_source=newest[0].name if newest else None
            job.status='Running'
        rows=source_rows(job);notes=[]
        for row in rows[:50]:
            if row.channel!=old.channel:frappe.throw('Legacy message channel does not match its conversation')
            bundle=job.flags.get('legacy_bundle')
            source_identity=(bundle['manifest']['source_site']+':'+row.name) if bundle else row.name
            source_key=hashlib.sha256(('frappe_whatsapp_core:'+source_identity).encode()).hexdigest()
            key=provider_key(job.channel,endpoint,row.provider_message_id) if row.provider_message_id else None
            existing=frappe.db.get_value('Relay Message',{'source_key':source_key},['name','relay_contact','channel'],as_dict=True)
            if not existing and key:existing=frappe.db.get_value('Relay Message',{'provider_message_key':key},['name','relay_contact','channel'],as_dict=True)
            if existing:
                if existing.relay_contact!=job.relay_contact or existing.channel!=job.channel:frappe.throw('Legacy message is already mapped to another conversation')
                job.skipped=(job.skipped or 0)+1;job.last_source=row.name;continue
            if row.direction not in ('Inbound','Outbound'):frappe.throw('Unknown legacy message direction')
            data,quote,file_url,warnings=converted(row)
            context=dict(base_context,message_id=row.provider_message_id)
            if quote:context['reply_to_message_id']=quote
            status={'Received':'Delivered','Queued':'Pending','Deleted':'Delivered'}.get(row.delivery_status,row.delivery_status)
            if status not in ('Pending','Sent','Delivered','Read','Failed'):status='Delivered' if row.direction=='Inbound' else 'Pending'
            message=frappe.get_doc(dict(doctype='Relay Message',relay_contact=job.relay_contact,channel=job.channel,
                direction='Incoming' if row.direction=='Inbound' else 'Outgoing',status=status,
                content=data.get('text') or data.get('caption') or row.body or '',message_type=data['kind'],
                message_data=json.dumps(data,ensure_ascii=False),provider_id=row.provider_message_id,sender_endpoint=endpoint,
                provider_context=json.dumps(context),provider_message_key=key,source_key=source_key,
                conversation_key=conversation_key(job.channel,endpoint,context),sent_at=row.provider_timestamp or row.creation,
                legacy_source=("bundle:"+source_key) if bundle else row.name,legacy_data=frappe.as_json(dict(row,source_site=bundle["manifest"]["source_site"] if bundle else frappe.local.site)))).insert()
            attachment=bundle['files'].get(row.name) if bundle else local_attachment(row,file_url)
            if attachment:
                if bundle:raw=attachment['content'];filename=attachment['filename']
                else:
                    file=frappe.get_doc('File',attachment);file.check_permission('read')
                    raw=file.get_content();raw=raw.encode() if isinstance(raw,str) else raw;filename=file.file_name
                if len(raw)>4*1024*1024:
                    warnings.append('Local attachment exceeds current 4 MiB viewer limit; retained in legacy app')
                else:
                    from frappe.utils.file_manager import save_file
                    copied=save_file(filename,raw,'Relay Message',message.name,is_private=1)
                    data.update(attachment=copied.name,attachment_source=message.name)
                    if data['kind'] in ('text','unsupported'):data.update(kind='document',caption=row.body or '')
                    frappe.db.set_value('Relay Message',message.name,{'message_data':json.dumps(data,ensure_ascii=False),'message_type':data['kind']})
            elif row.message_type in MEDIA:warnings.append('No attached local file; historical provider media may have expired')
            if warnings:frappe.db.set_value('Relay Message',message.name,'legacy_data',frappe.as_json(dict(row,source_site=bundle['manifest']['source_site'] if bundle else frappe.local.site,import_warnings=warnings)))
            notes.extend(row.name+': '+item for item in warnings)
            job.imported=(job.imported or 0)+1;job.last_source=row.name
        if len(rows)<=50:job.status='Completed'
        if notes:job.warnings='\n'.join(filter(None,[job.warnings,'\n'.join(notes)]))
        save_job(job);frappe.db.commit()
        return {'status':job.status,'imported':job.imported,'skipped':job.skipped,'warnings':notes}
