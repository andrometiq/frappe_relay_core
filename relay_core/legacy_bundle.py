"""Portable bounded legacy-history bundles. No provider calls or source writes."""
import hashlib
import io
import json
import os
import re
from pathlib import Path
import zipfile
import frappe
from relay_core.permissions import require_access

MAX_BYTES=24*1024*1024


def export_conversation(conversation, destination, after=None):
    """Run locally on the source site as a System Manager; export at most 500 rows."""
    require_access(configure=True)
    from relay_core import legacy
    old=frappe.get_doc('WhatsApp Core Conversation',conversation);old.check_permission('read')
    identity=frappe.get_doc('WhatsApp Core Identity',old.remote_identity);identity.check_permission('read')
    filters={'conversation':conversation}
    if after:filters['name']=['>',after]
    rows=frappe.get_list(legacy.SOURCE,filters=filters,fields=legacy.FIELDS,order_by='name asc',page_length=501)
    more=len(rows)>500;rows=rows[:500]
    # Reuse the source app's read-only renderer for old rows without snapshots.
    if 'frappe_whatsapp_core' in frappe.get_installed_apps():
        from frappe_whatsapp_core.inbox import _attach_template_snapshots
        _attach_template_snapshots(rows)
    manifest={'format':'relay-legacy-history','version':1,'source_site':frappe.local.site,'source_conversation':old.name,
              'source_channel':old.channel,'endpoint':identity.normalized_value,'identifier_type':identity.identifier_type,
              'conversation_status':old.get('status'),'assigned_team':old.get('assigned_team'),'assigned_user':old.get('assigned_user'),
              'count':len(rows),'next':rows[-1].name if more else None,'attachments':{},'warnings':[]}
    assets={};size=0
    for row in rows:
        _,_,url,_=legacy.converted(row);name=legacy.local_attachment(row,url)
        if not name:continue
        file=frappe.get_doc('File',name);file.check_permission('read')
        try:content=file.get_content();content=content.encode() if isinstance(content,str) else content
        except (OSError,ValueError):manifest['warnings'].append(row.name+': local attachment is unavailable');continue
        digest=hashlib.sha256(content).hexdigest()
        if len(content)>4*1024*1024 or size+(0 if digest in assets else len(content))>16*1024*1024:
            manifest['warnings'].append(row.name+': attachment retained only on the source site because of the bundle size limit');continue
        manifest['attachments'][row.name]={'path':'files/'+digest,'sha256':digest,'filename':file.file_name}
        if digest not in assets:size+=len(content);assets[digest]=content
    messages=frappe.as_json([dict(row) for row in rows]).encode()
    manifest['messages_sha256']=hashlib.sha256(messages).hexdigest()
    if len(messages)+size>MAX_BYTES:frappe.throw('Conversation export segment is too large')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False));archive.writestr('messages.json',messages)
        for digest,content in assets.items():archive.writestr('files/'+digest,content)
    content=buffer.getvalue()
    if len(content)>MAX_BYTES:frappe.throw('Conversation bundle exceeds 24 MiB')
    target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as handle:handle.write(content)
    return {'count':len(rows),'next':manifest['next'],'attachments':len(manifest['attachments']),'warnings':len(manifest['warnings']),'sha256':hashlib.sha256(content).hexdigest()}


def decode(content):
    if not isinstance(content,bytes) or len(content)>MAX_BYTES:frappe.throw('Invalid legacy bundle size')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries=archive.infolist()
            if len(entries)>502 or len({entry.filename for entry in entries})!=len(entries) or sum(entry.file_size for entry in entries)>MAX_BYTES:raise ValueError()
            if any(entry.filename not in ('manifest.json','messages.json') and not re.fullmatch(r'files/[a-f0-9]{64}',entry.filename) for entry in entries):raise ValueError()
            if archive.getinfo('manifest.json').file_size>1024*1024:raise ValueError()
            manifest=json.loads(archive.read('manifest.json'));raw=archive.read('messages.json');rows=json.loads(raw)
            if manifest.get('format')!='relay-legacy-history' or manifest.get('version')!=1 or hashlib.sha256(raw).hexdigest()!=manifest.get('messages_sha256'):raise ValueError()
            if not isinstance(rows,list) or len(rows)>500 or len(rows)!=manifest.get('count'):raise ValueError()
            for key in ('source_site','source_conversation','source_channel','endpoint'):
                if not isinstance(manifest.get(key),str) or not 1<=len(manifest[key])<=200:raise ValueError()
            if not isinstance(manifest.get('warnings',[]),list) or any(not isinstance(note,str) or len(note)>2000 for note in manifest.get('warnings',[])):raise ValueError()
            if manifest.get('identifier_type') not in ('Phone','BSUID','Group'):raise ValueError()
            if not isinstance(manifest.get('attachments'),dict) or len(manifest['attachments'])>500:raise ValueError()
            names=set();files={}
            for row in rows:
                if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not 1<=len(row['name'])<=140 or row['name'] in names or row.get('conversation')!=manifest['source_conversation'] or row.get('channel')!=manifest['source_channel']:raise ValueError()
                names.add(row['name']);meta=manifest['attachments'].get(row['name'])
                if meta:
                    if not isinstance(meta,dict) or not re.fullmatch(r'files/[a-f0-9]{64}',meta.get('path','')) or not isinstance(meta.get('filename'),str) or len(meta['filename'])>255:raise ValueError()
                    if archive.getinfo(meta['path']).file_size>4*1024*1024:raise ValueError()
                    data=archive.read(meta['path'])
                    if hashlib.sha256(data).hexdigest()!=meta.get('sha256'):raise ValueError()
                    files[row['name']]={'filename':Path(meta['filename'].replace('\\','/')).name,'content':data}
            return {'manifest':manifest,'rows':[frappe._dict(row) for row in sorted(rows,key=lambda row:row['name'])],'files':files,'sha256':hashlib.sha256(content).hexdigest()}
    except (ValueError,TypeError,KeyError,zipfile.BadZipFile,UnicodeDecodeError,RuntimeError,NotImplementedError):
        frappe.throw('Legacy bundle is malformed or its content checksum does not match')


def load(file_name):
    require_access(configure=True)
    file=frappe.get_doc('File',file_name);file.check_permission('read')
    if not file.is_private:frappe.throw('Legacy bundles must be stored as private files')
    content=file.get_content();content=content.encode() if isinstance(content,str) else content
    return decode(content)


@frappe.whitelist(methods=['GET'])
def details(file):
    bundle=load(file);manifest=bundle['manifest']
    return {key:manifest.get(key) for key in ('source_site','source_conversation','count','next')}
