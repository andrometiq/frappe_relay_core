"""Call history and signaling projected through verified conversation bindings."""
import hashlib
import json
import re
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.settings import value as connection_value
from relay_core.automation.service import internal_save
from relay_core.timeline import provider_time


def active_channel():
    names=frappe.get_all('Relay Channel',filters={'channel':'WhatsApp','enabled':1,'account':connection_value('relay_hub_account')},pluck='name',limit_page_length=2)
    if len(names)!=1:frappe.throw('Configure one active WhatsApp channel')
    doc=frappe.get_doc('Relay Channel',names[0]);doc.check_permission('read');return doc


def binding(channel, endpoint):
    key=hashlib.sha256((channel+':'+endpoint).encode()).hexdigest()
    return frappe.db.get_value('Relay Contact Endpoint',{'endpoint_key':key,'verified':1},'relay_contact')


def call_key(channel, identifier):return hashlib.sha256((channel+':'+identifier).encode()).hexdigest()


def readable(doc, active=False):
    readable_contact(doc.relay_contact)
    channel=frappe.get_doc('Relay Channel',doc.channel);channel.check_permission('read')
    if active and (not channel.enabled or channel.account!=connection_value('relay_hub_account') or binding(channel.name,doc.endpoint)!=doc.relay_contact):
        frappe.throw('Call channel or contact binding is unavailable',frappe.PermissionError)
    return doc


def authorize(payload, contact=None):
    channel=active_channel()
    if payload.get('action')=='connect':
        relay=binding(channel.name,payload.get('to',''))
        if not relay:frappe.throw('Verify the contact’s WhatsApp endpoint before calling',frappe.PermissionError)
        doc,person=readable_contact(relay)
        if person.name!=contact:frappe.throw('Call destination belongs to another contact',frappe.PermissionError)
        return channel.name,relay
    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(channel.name,payload.get('id',''))},'name')
    if not name:frappe.throw('The call is not available in this site',frappe.PermissionError)
    doc=readable(frappe.get_doc('Relay Call',name),active=True)
    return channel.name,doc.relay_contact


def record_outgoing(payload,result,channel,contact):
    identifier=(result.get('calls') or [{}])[0].get('id') or result.get('id')
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_.=:-]{1,512}',identifier):return
    key=call_key(channel,identifier)
    if frappe.db.exists('Relay Call',{'provider_key':key}):return
    doc=frappe.get_doc(dict(doctype='Relay Call',provider_key=key,provider_id=identifier,channel=channel,relay_contact=contact,
        endpoint=payload['to'],direction='Outgoing',state='Dialing',started_at=frappe.utils.now_datetime(),session='{}'))
    internal_save(doc,new=True)


def ingest(payload,channel):
    unresolved=False
    for entry in payload.get('entry',[])[:100]:
        for change in entry.get('changes',[])[:100]:
            for call in (change.get('value',{}).get('calls') or [])[:100]:
                identifier=call.get('id');stamp=provider_time({},call)
                if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_.=:-]{1,512}',identifier) or not stamp:continue
                key=call_key(channel,identifier)
                name=frappe.db.get_value('Relay Call',{'provider_key':key},'name',for_update=True)
                doc=frappe.get_doc('Relay Call',name) if name else None
                if not doc:
                    endpoint=next((str(call.get(field,'')) for field in ('from','to') if binding(channel,str(call.get(field,'')))),None)
                    contact=binding(channel,endpoint) if endpoint else None
                    if not contact:unresolved=True;continue
                    doc=frappe.get_doc(dict(doctype='Relay Call',provider_key=key,provider_id=identifier,channel=channel,relay_contact=contact,endpoint=endpoint,
                        direction='Outgoing' if call.get('direction')=='BUSINESS_INITIATED' else 'Incoming',state='Incoming',started_at=stamp,session='{}'))
                if doc.last_event_at and frappe.utils.get_datetime(doc.last_event_at)>stamp:continue
                event=call.get('event','')
                if doc.state in ('Ended','Rejected','Failed') and event!='terminate':continue
                if event=='terminate':
                    if doc.state!='Rejected':doc.state='Ended'
                    doc.ended_at=stamp;doc.session='{}'
                    duration=call.get('duration')
                    if isinstance(duration,int) and not isinstance(duration,bool) and 0<=duration<=86400:doc.duration=duration
                elif event in ('ringing','connect','accept'):
                    session=call.get('session') or {}
                    sdp=session.get('sdp','');kind=session.get('sdp_type')
                    if isinstance(sdp,str) and sdp.startswith('v=0') and len(sdp)<=60000 and kind in ('offer','answer'):
                        doc.session=json.dumps({'sdp':sdp,'sdp_type':kind})
                    doc.state='Incoming' if kind=='offer' else 'Connecting' if kind=='answer' else 'Ringing'
                else:continue
                doc.last_event_at=stamp
                if isinstance(doc.session,dict):doc.session=json.dumps(doc.session)
                internal_save(doc,new=not name)
                correlate_attempt(doc,call)
    return unresolved


@frappe.whitelist(methods=['GET'])
def history(contact=None, before=None):
    require_access()
    if contact:readable_contact(contact)
    if before and (not isinstance(before,str) or not re.fullmatch(r'RELAY-CALL-[0-9]{10}',before)):frappe.throw('Invalid call cursor')
    filters={}
    if contact:filters['relay_contact']=contact
    if before:filters['name']=['<',before]
    rows=frappe.get_all('Relay Call',filters=filters,fields=['name','provider_id','relay_contact','channel','endpoint','direction','state','started_at','ended_at','duration'],order_by='name desc',limit_page_length=31)
    items=[]
    for row in rows[:30]:
        try:readable(row)
        except frappe.PermissionError:continue
        row['display_name']=frappe.db.get_value('Relay Contact',row.relay_contact,'display_name');items.append(row)
    return {'items':items,'before':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def events(after=None):
    require_access();channel=active_channel()
    if after and (not isinstance(after,str) or not after.isdigit()):frappe.throw('Invalid call event cursor')
    from relay_core.whatsapp import checked_client
    hub,_=checked_client()
    result=hub.execute({'operation':'events.list','after':after} if after else {'operation':'events.latest'})
    output=[]
    for event in result.get('events',[])[:100]:
        payload=event.get('payload') or {};ingest(payload,channel.name)
        safe=[]
        for entry in payload.get('entry',[])[:100]:
            for change in entry.get('changes',[])[:100]:
                for call in (change.get('value',{}).get('calls') or [])[:100]:
                    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(channel.name,str(call.get('id','')))},'name')
                    if not name:continue
                    doc=frappe.get_doc('Relay Call',name)
                    try:readable(doc,active=True)
                    except frappe.PermissionError:continue
                    stamp=provider_time({},call)
                    if not stamp or abs((frappe.utils.now_datetime()-stamp).total_seconds())>300:continue
                    item={key:call[key] for key in ('id','event','timestamp') if key in call}
                    # Only current signaling survives; older/raw events never leak unrelated messages.
                    if doc.state not in ('Ended','Rejected','Failed') and doc.last_event_at and frappe.utils.get_datetime(doc.last_event_at)==stamp:
                        item['session']=frappe.parse_json(doc.session or '{}')
                    item['contact']=doc.relay_contact;safe.append(item)
        if safe:output.append({'id':event.get('id'),'payload':{'entry':[{'changes':[{'value':{'calls':safe}}]}]}})
    frappe.db.commit()
    return {'events':output,'next':result.get('next')}


def record_action(payload, channel):
    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(channel,payload.get('id',''))},'name')
    if not name:return
    doc=frappe.get_doc('Relay Call',name)
    if payload.get('action') in ('reject','terminate'):
        doc.state='Rejected' if payload['action']=='reject' else 'Ended';doc.ended_at=frappe.utils.now_datetime();doc.session='{}'
    elif payload.get('action') in ('accept','pre_accept') and doc.state not in ('Ended','Rejected','Failed'):
        doc.state='Connecting';doc.session='{}'
    else:return
    internal_save(doc)


def connected(provider_id):
    require_access();channel=active_channel()
    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(channel.name,provider_id)},'name')
    if not name:frappe.throw('Call is unavailable',frappe.PermissionError)
    doc=readable(frappe.get_doc('Relay Call',name),active=True)
    if doc.state not in ('Ended','Rejected','Failed'):
        doc.state='Connected';doc.session='{}';internal_save(doc)
    return {'state':doc.state}


def _store_recording(provider_id, content):
    require_access();channel=active_channel()
    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(channel.name,provider_id)},'name')
    if not name:frappe.throw('Call is unavailable',frappe.PermissionError)
    doc=readable(frappe.get_doc('Relay Call',name))
    maximum=recording_limits()['max_bytes']
    if not isinstance(content,bytes) or not 16<=len(content)<=maximum:frappe.throw('Recording exceeds the site upload limit or is empty')
    if content.startswith(b'\x1a\x45\xdf\xa3'):mime,extension='audio/webm','webm'
    elif content.startswith(b'OggS'):mime,extension='audio/ogg','ogg'
    elif content[4:8]==b'ftyp':mime,extension='audio/mp4','m4a'
    else:frappe.throw('Choose a WebM, Ogg or MP4 audio recording')
    checksum=hashlib.sha256(content).hexdigest()
    key=hashlib.sha256((doc.name+':'+frappe.session.user+':'+checksum).encode()).hexdigest()
    with frappe.cache.lock('relay-call-recording-'+key,timeout=30,blocking_timeout=3):
        existing=frappe.db.get_value('Relay Call Recording',{'recording_key':key},'name')
        if existing:return {'name':existing}
        record=frappe.get_doc(dict(doctype='Relay Call Recording',call=doc.name,uploaded_by=frappe.session.user,checksum=checksum,
                                   recording_key=key,content_type=mime,file_size=len(content)))
        internal_save(record,new=True)
        file=frappe.get_doc(dict(doctype='File',file_name='relay-call.'+extension,is_private=1,content=content,
                                attached_to_doctype='Relay Call Recording',attached_to_name=record.name)).insert(ignore_permissions=True)
        record.file=file.name;internal_save(record);frappe.db.commit()
    return {'name':record.name}


def upload_recording(provider_id):
    require_access()
    upload=frappe.request.files.get('file')
    if not upload:frappe.throw('Choose a recording')
    return _store_recording(provider_id,upload.stream.read(32*1024*1024+1))


@frappe.whitelist(methods=['GET'])
def recordings(call):
    require_access();readable(frappe.get_doc('Relay Call',call))
    return frappe.get_all('Relay Call Recording',filters={'call':call},fields=['name','creation','uploaded_by','file_size','content_type'],order_by='creation desc',limit_page_length=30)


def recording_content(name):
    require_access();record=frappe.get_doc('Relay Call Recording',name);readable(frappe.get_doc('Relay Call',record.call))
    file=frappe.get_doc('File',record.file)
    if not file.is_private or file.attached_to_doctype!='Relay Call Recording' or file.attached_to_name!=record.name:
        frappe.throw('Recording file binding is invalid',frappe.PermissionError)
    content=file.get_content()
    if isinstance(content,str):content=content.encode("utf-8")
    if not isinstance(content,bytes) or len(content)!=record.file_size or hashlib.sha256(content).hexdigest()!=record.checksum:
        frappe.throw('Recording file is missing or changed')
    return record,content


@frappe.whitelist(methods=['GET'])
def download_recording(name):
    record,content=recording_content(name)
    extension={'audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'m4a'}[record.content_type]
    frappe.local.response.filename='relay-call-'+record.call+'.'+extension
    frappe.local.response.filecontent=content
    frappe.local.response.type='download'
    frappe.local.response.content_type=record.content_type
    frappe.local.response.display_content_as='attachment'


@frappe.whitelist(methods=['GET'])
def recording_limits():
    require_access()
    from frappe.core.api.file import get_max_file_size
    return {'max_bytes':min(32*1024*1024,get_max_file_size())}



def admit_call(payload,channel,contact,request_key):
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',request_key):frappe.throw('A stable call request key is required')
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    lock=call_key(channel,payload['to'])
    with frappe.cache.lock('relay-call-admission:'+lock,timeout=30,blocking_timeout=3):
        name=frappe.db.get_value('Relay Call Attempt',{'request_key':key},'name')
        if name:
            attempt=frappe.get_doc('Relay Call Attempt',name)
            if attempt.channel!=channel or attempt.relay_contact!=contact or attempt.endpoint!=payload['to']:frappe.throw('Call request key was used for another destination')
            return attempt,False
        pending=frappe.db.get_value('Relay Call Attempt',{'channel':channel,'endpoint':payload['to'],'state':'Uncertain'},'name')
        if pending:return frappe.get_doc('Relay Call Attempt',pending),False
        active=frappe.db.exists('Relay Call',{'channel':channel,'endpoint':payload['to'],'state':['in',['Incoming','Dialing','Ringing','Connecting','Connected']]})
        if active:frappe.throw('End the existing call before starting another')
        attempt=frappe.get_doc(dict(doctype='Relay Call Attempt',request_key=key,channel=channel,relay_contact=contact,endpoint=payload['to'],requested_by=frappe.session.user,started_at=frappe.utils.now_datetime(),state='Uncertain'))
        internal_save(attempt,new=True);frappe.db.commit()
        return attempt,True


def attempt_result(attempt):
    if attempt.state=='Rejected':return {'call_attempt':attempt.name,'rejected':True}
    if attempt.provider_call:
        call=readable(frappe.get_doc('Relay Call',attempt.provider_call),active=True)
        return {'call_attempt':attempt.name,'contact':attempt.relay_contact,'calls':[{'id':call.provider_id}],'state':call.state,'recovered':True}
    return {'call_attempt':attempt.name,'contact':attempt.relay_contact,'outcome_unknown':True}


def confirm_attempt(attempt,provider_id):
    name=frappe.db.get_value('Relay Call',{'provider_key':call_key(attempt.channel,provider_id)},'name')
    if name:
        attempt.reload();attempt.provider_call=name;attempt.state='Confirmed';internal_save(attempt);frappe.db.commit()


def correlate_attempt(call,event):
    callback=event.get('biz_opaque_callback_data')
    if call.direction!='Outgoing' or not isinstance(callback,str) or not re.fullmatch(r'relay-call:[a-f0-9]{64}',callback):return
    name=frappe.db.get_value('Relay Call Attempt',{'request_key':callback.removeprefix('relay-call:'),'channel':call.channel,'endpoint':call.endpoint,'state':'Uncertain'},'name',for_update=True)
    if not name:return
    attempt=frappe.get_doc('Relay Call Attempt',name);attempt.provider_call=call.name;attempt.state='Confirmed';internal_save(attempt)


@frappe.whitelist(methods=['GET'])
def pending_call():
    require_access()
    rows=frappe.get_all('Relay Call Attempt',filters={'requested_by':frappe.session.user},fields=['name'],order_by='name desc',limit_page_length=20)
    for row in rows:
        attempt=frappe.get_doc('Relay Call Attempt',row.name)
        try:
            readable_contact(attempt.relay_contact)
            channel=frappe.get_doc('Relay Channel',attempt.channel);channel.check_permission('read')
            if not channel.enabled or channel.account!=connection_value('relay_hub_account'):continue
            result=attempt_result(attempt)
            if result.get('rejected'):continue
        except frappe.PermissionError:continue
        if result.get('outcome_unknown') or result.get('state') not in ('Ended','Rejected','Failed'):return result
    return {}


@frappe.whitelist(methods=['GET'])
def uncertain_attempts(contact=None, before=None):
    require_access()
    from relay_core.permissions import MANAGER
    can_resolve = bool(set(frappe.get_roles()).intersection({'System Manager', MANAGER}))
    filters = {'state': 'Uncertain'}
    if not can_resolve:
        filters['requested_by'] = frappe.session.user
    if contact:
        readable_contact(contact)
        filters['relay_contact'] = contact
    if before:
        if not isinstance(before, str) or len(before) > 140:
            frappe.throw('Invalid call cursor')
        filters['name'] = ['<', before]
    rows = frappe.get_all('Relay Call Attempt', filters=filters, fields=['name', 'relay_contact', 'channel', 'started_at', 'requested_by'], order_by='name desc', limit_page_length=31)
    items = []
    for row in rows[:30]:
        try:
            readable_contact(row.relay_contact)
            frappe.get_doc('Relay Channel', row.channel).check_permission('read')
        except frappe.PermissionError:
            continue
        items.append(row)
    return {'items': items, 'before': rows[29].name if len(rows) > 30 else None, 'can_resolve': can_resolve}


def resolve_attempt(name, outcome, evidence, provider_id=None):
    """Record verified operator evidence without issuing any provider request."""
    require_access(manage=True)
    if outcome not in {'Not started', 'Existing call'}:
        frappe.throw('Choose a verified call outcome')
    if not isinstance(evidence, str) or not 10 <= len(evidence.strip()) <= 2000:
        frappe.throw('Describe how the call outcome was verified (10–2000 characters)')
    if outcome == 'Not started' and provider_id:
        frappe.throw('A call ID applies only to an existing call')
    if outcome == 'Existing call' and (not isinstance(provider_id, str) or not re.fullmatch(r'[A-Za-z0-9_.=:-]{1,512}', provider_id)):
        frappe.throw('Enter the verified provider call ID')
    doc = frappe.get_doc('Relay Call Attempt', name)
    readable_contact(doc.relay_contact)
    frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
    with frappe.cache.lock('relay-call-admission:' + call_key(doc.channel, doc.endpoint), timeout=30, blocking_timeout=3):
        frappe.db.get_value('Relay Call Attempt', name, 'name', for_update=True)
        doc.reload()
        linked = None
        if outcome == 'Existing call':
            linked = frappe.db.get_value('Relay Call', {'provider_key': call_key(doc.channel, provider_id)}, 'name')
            if not linked:
                frappe.throw('Wait for the verified call to appear in call history before linking it')
            call = readable(frappe.get_doc('Relay Call', linked))
            if call.direction != 'Outgoing' or call.relay_contact != doc.relay_contact or call.endpoint != doc.endpoint:
                frappe.throw('The call does not match this attempt', frappe.PermissionError)
        if doc.resolution:
            if doc.resolution == outcome and doc.resolution_note == evidence.strip() and (doc.provider_call or None) == linked:
                return {'name': doc.name, 'state': doc.state}
            frappe.throw('This call attempt was already resolved')
        if doc.state != 'Uncertain':
            frappe.throw('This attempt has already been confirmed. Refresh call history.')
        doc.state = 'Rejected' if outcome == 'Not started' else 'Confirmed'
        doc.provider_call = linked
        doc.resolution = outcome
        doc.resolution_note = evidence.strip()
        doc.resolved_by = frappe.session.user
        doc.resolved_at = frappe.utils.now_datetime()
        internal_save(doc)
        frappe.db.commit()
        return {'name': doc.name, 'state': doc.state}
