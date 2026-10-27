"""Versioned slash-command flows with journaled input and scoped actions."""
import hashlib
import json
import re
import frappe
from relay_core.automation.queue import QUEUE, after_message_commit
from relay_core.permissions import require_access, readable_contact, can_configure
from relay_core.automation.service import internal_save, check_actor, business_scope, message_hash
from relay_core.automation.provenance import context_of, conversation_key
from relay_core.flows.contracts import definition, parse_input, render, matches, choice_options


def digest(*parts):
    return hashlib.sha256(':'.join(str(part) for part in parts).encode()).hexdigest()


def validate_flow(doc):
    require_access(configure=True)
    if not isinstance(doc.title,str) or not 1<=len(doc.title.strip())<=140:
        frappe.throw('Flow title must contain 1–140 characters')
    if not isinstance(doc.command,str) or not re.fullmatch(r'/[a-z][a-z0-9_]{0,31}',doc.command):
        frappe.throw('Choose a slash command such as /support')
    validated=definition(doc.nodes)
    from relay_core.flows.actions import definitions
    registered=definitions(context='flow')
    if any(node['kind']=='action' and node['action'] not in registered for node in validated):
        frappe.throw('Choose an installed, replay-safe business action')
    check_actor(doc)
    if not frappe.db.exists('Relay Contact Type',{'business_doctype':doc.business_doctype,'enabled':1}):
        frappe.throw('Choose a configured business type')
    channel=frappe.get_doc('Relay Channel',doc.channel);channel.check_permission('read')
    if channel.channel!='WhatsApp' or not channel.enabled:frappe.throw('Choose an enabled WhatsApp channel')
    doc.trigger_key=digest(doc.channel,doc.command)
    button=doc.get('template_button') or ''
    if not isinstance(button,str) or len(button)>140:frappe.throw('Template button payload must contain at most 140 characters')
    doc.button_key=digest(doc.channel,button) if button else None
    previous=doc.get_doc_before_save()
    if (doc.published_version or '') != ((previous.published_version or '') if previous else '') and not getattr(frappe.flags,'relay_automation_internal',False):
        frappe.throw('Publish flow versions through the workflow service')
    if doc.enabled and not doc.published_version:
        frappe.throw('Publish a version before enabling the flow')


@frappe.whitelist(methods=['GET'])
def directory(after=None,query=''):
    require_access(manage=True)
    if not isinstance(query,str) or len(query)>80:
        frappe.throw('Invalid flow search')
    filters={'name':['>',after]} if after else {}
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=frappe.get_list('Relay Flow',filters=filters,
        or_filters=[['title','like',needle],['command','like',needle]],
        fields=['name','title','command','channel','enabled','published_version'],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None,
            'can_configure':can_configure()}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access(manage=True)
    doc=frappe.get_doc('Relay Flow',name);doc.check_permission('read')
    result={key:doc.get(key) for key in ('name','title','command','channel','execution_user','business_doctype','enabled','nodes','published_version','template_button')}
    result['published_nodes']=None
    if doc.published_version:
        version=frappe.get_doc('Relay Flow Version',doc.published_version)
        if version.flow!=doc.name:frappe.throw('Published workflow version is invalid')
        result['published_nodes']=version.nodes
    return result


@frappe.whitelist(methods=['GET'])
def providers(query='',after=None):
    """Return enabled AI Models with enabled provider accounts."""
    require_access(configure=True)
    if not isinstance(query,str) or len(query)>80 or (after is not None and (not isinstance(after,str) or len(after)>140)):
        frappe.throw('Invalid provider search')
    accounts = frappe.get_list('AI Provider Account', filters={'enabled': 1}, pluck='name', page_length=0)
    filters={'enabled':1, 'account':['in', accounts]}
    if after:filters['name']=['>',after]
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=frappe.get_list('AI Model',filters=filters,
        or_filters=[['model_id','like',needle],['provider','like',needle]],
        fields=['name','provider','model_id as model'],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def references(kind,query=''):
    """Search only runtime values accepted by WhatsApp flow validation."""
    require_access(configure=True)
    if not isinstance(query,str) or len(query)>80:
        frappe.throw('Invalid reference search')
    if kind=='channel':
        needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        rows=frappe.get_list('Relay Channel',filters={'channel':'WhatsApp','enabled':1},
            or_filters=[['name','like',needle],['account','like',needle]],
            fields=['name','account'],order_by='name asc',page_length=30)
        return [{'value':row.name,'label':' · '.join(filter(None,(row.name,row.account)))} for row in rows]
    if kind not in ('execution_user','business_doctype'):
        frappe.throw('Invalid flow reference')
    from relay_core.automation.settings import references as automation_references
    return automation_references(kind,query)


@frappe.whitelist(methods=['POST'])
def save(values,name=None):
    require_access(configure=True)
    if isinstance(values,str):values=frappe.parse_json(values)
    allowed={'title','command','channel','execution_user','business_doctype','enabled','nodes','template_button'}
    if not isinstance(values,dict) or set(values)-allowed:frappe.throw('Invalid flow fields')
    if 'nodes' in values:values=dict(values,nodes=json.dumps(definition(values['nodes'])))
    doc=frappe.get_doc('Relay Flow',name) if name else frappe.new_doc('Relay Flow')
    doc.update(values);doc.save()
    return read(doc.name)


@frappe.whitelist(methods=['POST'])
def validate_draft(values,name=None):
    """Validate a complete AI-authored draft without writing it."""
    require_access(configure=True)
    if isinstance(values,str):values=frappe.parse_json(values)
    allowed={'title','command','channel','execution_user','business_doctype','enabled','nodes','template_button'}
    if not isinstance(values,dict) or set(values)-allowed:frappe.throw('Invalid flow fields')
    doc=frappe.get_doc('Relay Flow',name) if name else frappe.new_doc('Relay Flow')
    doc.update(values)
    validate_flow(doc)
    return {
        'valid':True,
        'name':doc.name if name else None,
        'title':doc.title,
        'command':doc.command,
        'channel':doc.channel,
        'execution_user':doc.execution_user,
        'business_doctype':doc.business_doctype,
        'enabled':int(doc.enabled or 0),
        'nodes':definition(doc.nodes),
        'template_button':doc.get('template_button') or '',
    }


@frappe.whitelist(methods=['POST'])
def publish(name):
    require_access(configure=True)
    with frappe.cache.lock('relay-flow-publish-'+name,timeout=15,blocking_timeout=3):
        doc=frappe.get_doc('Relay Flow',name);doc.check_permission('write')
        data={key:doc.get(key) for key in ('nodes','channel','execution_user','business_doctype','template_button')}
        version=frappe.get_doc({'doctype':'Relay Flow Version','flow':doc.name,**data,
                              'definition_hash':digest(json.dumps(data,sort_keys=True))})
        internal_save(version,new=True);doc.published_version=version.name
        internal_save(doc);frappe.db.commit()
    return read(name)


@frappe.whitelist(methods=['POST'])
def set_enabled(name,enabled):
    """Enable or disable a published flow through an explicit MCP-safe action."""
    require_access(configure=True)
    if enabled not in (0,1,False,True,'0','1'):
        frappe.throw('Enabled must be 0 or 1')
    with frappe.cache.lock('relay-flow-state-'+name,timeout=15,blocking_timeout=3):
        doc=frappe.get_doc('Relay Flow',name);doc.check_permission('write')
        doc.enabled=int(str(enabled) in ('1','True'))
        doc.save()
    return read(name)


def route(message):
    context=context_of(message)
    from relay_core.business_access import reference
    business=reference(message)
    # The business record is part of the route. A shared Contact can therefore
    # never resume a workflow that belongs to another business timeline.
    return digest(conversation_key(message.channel,message.sender_endpoint or '',context),
        *(business or ('','')))


def matching(message):
    if message.get('legacy_source') or message.direction!='Incoming' or message.message_type not in ('',None,'text'):
        return None
    context=context_of(message)
    if context.get('provider')!='WhatsApp':return None
    if context.get('provider')=='WhatsApp' and context.get('original_message_type')=='button':
        data=message.get('message_data') or {}
        if isinstance(data,str):data=json.loads(data)
        payload=data.get('selection_id') if isinstance(data,dict) and data.get('selection_type')=='template_button' else None
        if isinstance(payload,str) and payload:
            return frappe.db.get_value('Relay Flow',{'button_key':digest(message.channel,payload),'enabled':1},'name')
    command=(message.content or '').strip()
    if re.fullmatch(r'/[a-z][a-z0-9_]{0,31}',command):
        return frappe.db.get_value('Relay Flow',{'trigger_key':digest(message.channel,command),'enabled':1},'name')
    return None


def active(key):
    return frappe.db.get_value('Relay Flow Run',{'conversation_key':key,'status':['in',['Running','Waiting']]},'name',order_by='name desc')


def claims(message):
    if message.get('legacy_source') or message.direction!='Incoming' or message.message_type not in ('',None,'text'):
        return False
    try:
        context=context_of(message)
    except (ValueError,TypeError):
        return False
    if context.get('provider')!='WhatsApp':return False
    return bool(matching(message) or active(route(message)) or frappe.db.exists(
        'Relay Flow Event', {'conversation_key': route(message), 'status': 'Pending'}))


@after_message_commit
def on_message(doc,method=None):
    from relay_core.automation.service import create_run
    return create_run(doc)


def create_event(doc):
    """Internal flow intent; only the shared inbound admission calls this."""
    if frappe.db.exists('Relay Flow Event',{'message':doc.name}):return
    event=frappe.get_doc({'doctype':'Relay Flow Event','message':doc.name,'message_hash':message_hash(doc),
                          'conversation_key':route(doc),'status':'Pending'})
    internal_save(event,new=True)
    frappe.enqueue('relay_core.flows.service.process',name=event.name,queue=QUEUE,enqueue_after_commit=True)


@frappe.whitelist(methods=['POST'])
def enqueue(message):
    require_access(manage=True)
    from relay_core.messaging import readable_source
    source,_,_=readable_source(message)
    on_message(source)
    return {'event':frappe.db.get_value('Relay Flow Event',{'message':message},'name')}


def scope(run,message, *, handoff=False):
    statuses = ('Handoff',) if handoff else ('Running', 'Waiting')
    if run.status not in statuses:
        raise ValueError('Flow is no longer active')
    flow=frappe.get_doc('Relay Flow',run.flow)
    version=frappe.get_doc('Relay Flow Version',run.version)
    if not flow.enabled or flow.published_version!=version.name:
        raise ValueError('Flow was changed or disabled')
    check_actor(version)
    frappe.set_user(version.execution_user)
    from relay_core.messaging import readable_source
    source,channel,context=readable_source(message.name)
    if channel.channel!='WhatsApp' or context.get('provider')!='WhatsApp' or context.get('group_id'):
        raise ValueError('Flows require a private WhatsApp conversation')
    if source.direction!='Incoming' or channel.name!=version.channel or route(source)!=run.conversation_key:
        raise ValueError('Flow conversation changed')
    contact,_=readable_contact(source.relay_contact)
    if source.get('ticket'):
        from relay_core.tickets import check_episode
        admission = frappe.db.get_value('Relay Automation Run', {'message': run.start_message},
            ['ticket', 'ownership_generation'], as_dict=True)
        if not admission or admission.ticket != source.ticket:
            raise ValueError('Flow episode changed')
        check_episode(admission)
    generation = int(run.generation or 0) + int(handoff)
    if bool(contact.automation_paused) != handoff or int(contact.automation_generation or 0) != generation:
        raise ValueError('A human has taken ownership of this conversation')
    from relay_core.business_access import reference,candidates
    target=(run.get('business_doctype'),run.get('business_name')) if run.get('business_name') else reference(source)
    if not target or target not in candidates(contact.name):raise ValueError('Flow business context is missing or ambiguous')
    if target[0]!=version.business_doctype:raise ValueError('Flow business type changed')
    if source.get('business_name') and target!=(source.business_doctype,source.business_name):raise ValueError('Flow message belongs to another business')
    frappe.get_doc(*target).check_permission('read')
    return version,source,channel


def send(run,event,source,channel,text,key):
    if channel.channel=='Email':
        from relay_core.email import send as email_send
        result=email_send([source.sender_endpoint],'Flow update',text,message=source.name,request_key=key,auto_submitted=1)
        if not result.get('message_id'):raise RuntimeError('Delivery not confirmed')
    else:
        from relay_core.messaging import send as message_send, outgoing_flow
        marker = {'name': run.name, 'version': run.version, 'generation': int(run.generation or 0)}
        if run.status == 'Handoff': marker['handoff'] = True
        token = outgoing_flow.set(marker)
        try:
            result=message_send(source.name,'text',{'text':text},key)
        finally:
            outgoing_flow.reset(token)
        if result.get('status')!='Submitted':raise RuntimeError('Delivery not confirmed')


def flow_ticket(source, text):
    from relay_core.tickets import ensure_episode
    actor = frappe.session.user
    try:
        frappe.set_user('Administrator')
        return ensure_episode(source, owner=actor, subject=text[:140] or 'Conversation needs a person', reason=text)
    finally:
        frappe.set_user(actor)


def next_step(nodes,index):
    target=nodes[index].get('next')
    return next(i for i,node in enumerate(nodes) if node['id']==target) if target else index+1


def finish(event):
    event.status='Complete';event.reason='';internal_save(event);frappe.db.commit()


def _process(event):
    message=frappe.get_doc('Relay Message',event.message)
    if message_hash(message)!=event.message_hash:raise ValueError('Input changed after it was queued')
    if event.run:
        run=frappe.get_doc('Relay Flow Run',event.run)
    else:
        flow_name=matching(message)
        current=active(event.conversation_key)
        if flow_name:
            if current:
                old=frappe.get_doc('Relay Flow Run',current);old.status='Cancelled';old.reason='Restarted by slash command';internal_save(old)
            flow=frappe.get_doc('Relay Flow',flow_name)
            contact=frappe.get_doc('Relay Contact',message.relay_contact)
            from relay_core.business_access import reference
            target=reference(message)
            if not target:raise ValueError('Flow business context is missing or ambiguous')
            run=frappe.get_doc({'doctype':'Relay Flow Run','flow':flow_name,'version':flow.published_version,
                'conversation_key':event.conversation_key,'start_message':message.name,'last_message':message.name,
                'relay_contact':message.relay_contact,'business_doctype':target[0],'business_name':target[1],
                'generation':contact.automation_generation or 0,
                'status':'Running','step':0,'values':'{}'})
            internal_save(run,new=True);event.input_applied=1
        elif current:
            run=frappe.get_doc('Relay Flow Run',current)
        else:
            event.status='Rejected';event.reason='No active flow';internal_save(event);frappe.db.commit();return
        event.run=run.name;internal_save(event);frappe.db.commit()
    if run.status not in ('Running','Waiting'):
        finish(event);return
    version,source,channel=scope(run,message)
    run.reason=''
    nodes=definition(version.nodes);values=json.loads(run.get('values') or '{}')
    if run.status=='Waiting' and not event.input_applied:
        node=nodes[run.step]
        try:value=parse_input(node,message.content)
        except ValueError as error:
            send(run,event,source,channel,str(error)+'\n'+render(node['text'],values),'flow-'+event.name+'-invalid')
            finish(event);return
        values[node['variable']]=value
        run.values=json.dumps(values);run.step=next_step(nodes,run.step);run.status='Running';run.last_message=message.name
        event.input_applied=1;internal_save(run);internal_save(event);frappe.db.commit()
    elif run.status=='Waiting':
        finish(event);return
    # Bound one job to five side effects. Remaining steps resume from persisted state.
    for _ in range(5):
        if run.step>=len(nodes):
            run.status='Completed';internal_save(run);finish(event);return
        version,source,channel=scope(run,message)
        node=nodes[run.step];text=render(node['text'],values);key='flow-'+run.name+'-'+node['id']
        if node['kind']=='end':
            if text.strip():send(run,event,source,channel,text,key+'-end')
            run.status='Completed';internal_save(run);finish(event);return
        if node['kind']=='condition':
            target=node['then'] if matches(node,values) else node['otherwise']
            run.step=next(index for index,item in enumerate(nodes) if item['id']==target)
            internal_save(run);frappe.db.commit();continue
        if node['kind']=='wait':
            run.step=next_step(nodes,run.step)
            event.next_attempt=frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=node['seconds'])
            run.reason='Waiting until '+str(event.next_attempt);internal_save(run)
            internal_save(event);frappe.db.commit();return
        if node['kind']=='input':
            if node['input_type']=='choice':text+='\n'+', '.join(c['label'] for c in choice_options(node['choices']))
            if node['input_type']=='multi_choice':text+='\n'+'\n'.join(str(index+1)+'. '+choice['label'] for index,choice in enumerate(choice_options(node['choices'])))+'\nReply with choice numbers separated by commas.'
            if node.get('optional'):text+='\nReply skip to leave this blank.'
            send(run,event,source,channel,text,key+'-prompt');run.status='Waiting';internal_save(run);finish(event);return
        if node['kind']=='reply':
            send(run,event,source,channel,text,key)
        elif node['kind']=='ticket':
            flow_ticket(source, text)
        elif node['kind']=='action':
            from relay_core.flows.actions import execute
            execute(run,node,values,key)
        elif node['kind']=='topic':
            from relay_core.topics import upsert
            sources=frappe.get_all('Relay Flow Event',filters={'run':run.name,'input_applied':1},pluck='message',order_by='name asc',limit_page_length=501)
            if len(sources)>500:raise ValueError('Topic contains too many messages')
            upsert(run.relay_contact,{'title':render(node['title'],values)[:140],
                'summary':text,'category':node.get('category',''),'status':node.get('status','Open'),
                'messages':list(dict.fromkeys([run.start_message]+sources))},source='Flow',source_key=key)
        elif node['kind']=='handoff':
            ticket = flow_ticket(source, text)
            from relay_core.tickets import hold_episode
            hold_episode(ticket.name)
            run.status='Handoff';internal_save(run);finish(event)
            return
        run.step=next_step(nodes,run.step);internal_save(run);frappe.db.commit()
    frappe.enqueue('relay_core.flows.service.process',name=event.name,queue=QUEUE,enqueue_after_commit=True)


def process(name):
    actor=frappe.session.user
    event=frappe.get_doc('Relay Flow Event',name)
    with frappe.cache.lock('relay-flow-conversation-'+event.conversation_key,timeout=300,blocking_timeout=1):
        event.reload()
        if event.status!='Pending':return
        if event.next_attempt and frappe.utils.get_datetime(event.next_attempt)>frappe.utils.now_datetime():return
        first=None
        pending=frappe.get_all('Relay Flow Event',filters={'conversation_key':event.conversation_key,'status':'Pending'},fields=['name','run'],order_by='name asc',limit_page_length=100)
        for item in pending:
            if item.run and frappe.db.get_value('Relay Flow Run',item.run,'status') not in ('Running','Waiting'):
                finished=frappe.get_doc('Relay Flow Event',item.name);finish(finished)
                continue
            first=item.name;break
        if first!=event.name and not matching(frappe.get_doc('Relay Message',event.message)):return
        try:_process(event)
        except (frappe.PermissionError,frappe.ValidationError,ValueError):
            frappe.db.rollback();event.reload()
            if event.status == 'Complete': return
            event.status='Rejected';event.reason='Flow, input or conversation is no longer permitted'
            internal_save(event)
            if event.run:frappe.db.set_value('Relay Flow Run',event.run,{'status':'Cancelled','reason':event.reason})
            frappe.db.commit()
        except Exception:
            frappe.db.rollback();event.reload()
            if event.status == 'Complete': return
            event.attempts=int(event.attempts or 0)+1
            event.reason='Step not confirmed; recovery reuses the same action key'
            event.next_attempt=frappe.utils.add_to_date(frappe.utils.now_datetime(),minutes=min(60,2**min(event.attempts,6)))
            internal_save(event)
            if event.run:frappe.db.set_value('Relay Flow Run',event.run,'reason',event.reason)
            frappe.db.commit()
        finally:frappe.set_user(actor)


def recover():
    rows=frappe.get_all('Relay Flow Event',filters={'status':'Pending'},
        or_filters=[['next_attempt','is','not set'],['next_attempt','<=',frappe.utils.now_datetime()]],
        pluck='name',order_by='name asc',limit_page_length=30)
    for name in rows:frappe.enqueue('relay_core.flows.service.process',name=name,queue=QUEUE,job_id='relay-flow-'+name,deduplicate=True)


def readable_run(run):
    readable_contact(run.relay_contact)
    from relay_core.business_access import reference
    target = (run.business_doctype, run.business_name) if run.get('business_name') else None
    if not target and run.get('start_message'):
        source = frappe.get_doc('Relay Message', run.start_message)
        source.check_permission('read')
        target = reference(source)
    if not target:
        frappe.throw('Flow business context is unavailable', frappe.PermissionError)
    frappe.get_doc(*target).check_permission('read')
    return target


@frappe.whitelist(methods=['GET'])
def runs(flow,after=None):
    require_access(manage=True)
    read(flow)
    rows=frappe.get_all('Relay Flow Run',filters={'flow':flow,**({'name':['>',after]} if after else {})},
        fields=['name','relay_contact','business_doctype','business_name','start_message','status','step','reason','creation'],order_by='name asc',limit_page_length=31)
    items=[]
    for row in rows[:30]:
        try:readable_run(row)
        except frappe.PermissionError:continue
        row['display_name']=frappe.db.get_value('Relay Contact',row.relay_contact,'display_name')
        items.append(row)
    return {'items':items,'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['POST'])
def cancel(name):
    require_access(manage=True)
    run=frappe.get_doc('Relay Flow Run',name);readable_run(run)
    with frappe.cache.lock('relay-flow-conversation-'+run.conversation_key,timeout=10,blocking_timeout=3):
        run.reload()
        if run.status in ('Running','Waiting'):
            run.status='Cancelled';run.reason='Cancelled by an agent';internal_save(run)
        frappe.db.commit()
    return {'name':name,'status':run.status}


@frappe.whitelist(methods=['GET'])
def responses(name):
    require_access(manage=True)
    run=frappe.get_doc('Relay Flow Run',name);readable_run(run)
    read(run.flow)
    values=json.loads(run.get('values') or '{}')
    version=frappe.get_doc('Relay Flow Version',run.version)
    inputs={node['variable']:node['text'] for node in definition(version.nodes) if node['kind']=='input'}
    return {'name':run.name,'status':run.status,'contact':run.relay_contact,'business_doctype':run.get('business_doctype'),
            'business_name':run.get('business_name'),'start_message':run.start_message,'last_message':run.last_message,
            'responses':[{'field':key,'question':inputs.get(key,key),'answer':value} for key,value in values.items() if key in inputs]}


@frappe.whitelist(methods=['POST'])
def preview_legacy(graph):
    """Review conversion only. Saving and publishing remain explicit MCP actions."""
    require_access(configure=True)
    if isinstance(graph,str):
        if len(graph)>200000:frappe.throw('Legacy graph exceeds 200,000 characters')
        graph=frappe.parse_json(graph)
    if len(json.dumps(graph))>200000:frappe.throw('Legacy graph exceeds 200,000 characters')
    from relay_core.flows.legacy_graph import convert
    from relay_core.flows.actions import definitions
    result=convert(graph)
    registered=definitions(context='flow')
    missing=sorted({node['action'] for node in result['nodes'] if node['kind']=='action' and node['action'] not in registered})
    triggers=result['triggers']
    commands=[row.get('match') for row in triggers if isinstance(row,dict) and row.get('type')=='command']
    buttons=[row.get('match') for row in triggers if isinstance(row,dict) and row.get('type')=='template_button']
    if len(commands)!=1 or len(buttons)>1 or any(not isinstance(row,dict) or row.get('type') not in ('command','template_button') for row in triggers):frappe.throw('This import requires exactly one command and at most one template button trigger')
    result['command']=commands[0]
    result['template_button']=buttons[0] if buttons else ''
    result['missing_actions']=missing
    result['warnings']=['Review channel, execution user and business type before saving.',
                        'Imported flows remain disabled until reviewed and published.']
    return result
