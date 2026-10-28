"""Versioned slash-command flows with journaled input and scoped actions."""
import hashlib
import json
import re
import frappe
from relay_core.automation.queue import QUEUE, after_message_commit
from relay_core.permissions import require_access, readable_contact, can_manage
from relay_core.automation.service import internal_save, check_actor, message_hash
from relay_core.automation.provenance import context_of, conversation_key
from relay_core import features
from relay_core.flows.contracts import DEFAULT_VISITS, LAST_INPUT, definition, parse_input, prompt, render, matches

COMMAND = r'/[a-z][a-z0-9_]{0,31}'
FLOW_FIELDS = {'title', 'command', 'keywords', 'channel', 'execution_user', 'business_doctype', 'enabled', 'nodes', 'template_button'}
KEYWORD_CACHE = 'relay_flow_keywords'
EXIT_WORDS = {'exit', '/exit', 'cancel', '/cancel', 'stop', '/stop'}
RUN_DAYS = 7
CLAIMED_TYPES = {'', None, 'text', 'image', 'video', 'audio', 'voice', 'document', 'sticker', 'location', 'contact', 'contacts'}


def digest(*parts):
    return hashlib.sha256(':'.join(str(part) for part in parts).encode()).hexdigest()


def validate_flow(doc):
    require_access(manage=True)
    if not isinstance(doc.title,str) or not 1<=len(doc.title.strip())<=140:
        frappe.throw('Flow title must contain 1–140 characters')
    if doc.command and (not isinstance(doc.command,str) or not re.fullmatch(COMMAND,doc.command)):
        frappe.throw('Choose a slash command such as /support')
    doc.keywords='\n'.join(keywords(doc.get('keywords')))
    if not (doc.command or doc.keywords or doc.get('template_button')):
        frappe.throw('Choose a slash command, a keyword or a template button that starts the flow')
    validated=definition(doc.nodes)
    # Imported flows may name actions their business app has not registered yet; only an enabled flow needs them.
    if doc.enabled and missing_actions(validated):
        frappe.throw('Choose an installed, replay-safe business action')
    check_actor(doc)
    if not frappe.db.exists('Relay Contact Type',{'business_doctype':doc.business_doctype,'enabled':1}):
        frappe.throw('Choose a configured business type')
    channel=frappe.get_doc('Relay Channel',doc.channel);channel.check_permission('read')
    if channel.channel not in ('WhatsApp','Telegram','Email') or not channel.enabled:frappe.throw('Choose an enabled channel')
    doc.trigger_key=digest(doc.channel,doc.command) if doc.command else None
    check_keywords(doc)
    button=doc.get('template_button') or ''
    if not isinstance(button,str) or len(button)>140:frappe.throw('Template button payload must contain at most 140 characters')
    doc.button_key=digest(doc.channel,button) if button else None
    previous=doc.get_doc_before_save()
    if (doc.published_version or '') != ((previous.published_version or '') if previous else '') and not getattr(frappe.flags,'relay_automation_internal',False):
        frappe.throw('Publish flow versions through the workflow service')
    if doc.enabled and not doc.published_version:
        frappe.throw('Publish a version before enabling the flow')


def validate_compatibility(doc, nodes):
    from relay_core.automation.channel import validate_assignment, validate_skill
    from relay_core.flows.actions import definitions
    channel = frappe.get_doc('Relay Channel', doc.channel)
    if doc.get('template_button') and channel.channel != 'WhatsApp':
        frappe.throw('Template button triggers require WhatsApp')
    actions = definitions(context='flow')
    for node in nodes:
        if node['kind'] == 'ai_skill':
            validate_skill(node['ai_skill'], doc.channel, doc.business_doctype)
        elif node['kind'] == 'assign':
            validate_assignment(node.get('team'), node.get('user'))
        elif node['kind'] == 'action':
            action = actions.get(node['action'])
            if not action or channel.channel not in action.get('channels', ('WhatsApp', 'Telegram', 'Email')):
                frappe.throw('Business action is unavailable on this channel')
        elif channel.channel == 'Email' and node['kind'] == 'input' and node.get('input_type') == 'content':
            if 'text' not in node.get('accept', ['text']):
                frappe.throw('Email content questions must accept text')


def input_value(message, node):
    data = message.get('message_data') or {}
    if isinstance(data, str):
        data = json.loads(data)
    if node.get('input_type') == 'choice' and context_of(message).get('original_message_type') == 'interactive':
        return data.get('selection_id') or message.content
    return message.content


def send_prompt(run, event, source, channel, node, values, key):
    from relay_core.flows.contracts import choice_options
    data = None
    if channel.channel == 'WhatsApp' and node['input_type'] == 'choice' and not node.get('optional'):
        options = choice_options(node['choices'])
        body = render(node['text'], values)
        if len(options) <= 10 and len(body) <= 1024 and all(len(row['label']) <= (20 if len(options) <= 3 else 24) for row in options):
            modes = values.setdefault('_interactive', {})
            if key not in modes:
                from relay_core.whatsapp import checked_client
                _, capabilities = checked_client()
                modes[key] = 'messages.interactive' in capabilities.get('operations', [])
                run.values = json.dumps(values)
                internal_save(run)
            if modes[key]:
                data = {'body': body, 'choices': options, 'button': node.get('button') or 'Choose'}
    send(run, event, source, channel, prompt(node, values), key, choices=data)


def run_skill(run, event, source, node, key):
    from relay_core import ai_features
    from relay_core.ai.service import select_skill
    from relay_core.automation.service import lock_contact
    if not (frappe.conf.get('relay_automation_enabled') and ai_features.is_enabled()):
        raise ValueError('AI is disabled')
    identifier = digest('flow-skill', key)
    name = frappe.db.get_value('Relay Automation Run', {'event_key': identifier}, 'name', for_update=True)
    if not name:
        contact = lock_contact(source.relay_contact)
        from relay_core.automation.contracts import event_key
        admission = frappe.db.get_value('Relay Automation Run', {'event_key': event_key(run.start_message)},
                                        ['ticket', 'ownership_generation'], as_dict=True)
        child = frappe.get_doc(dict(doctype='Relay Automation Run', event_key=identifier, message=source.name,
            message_hash=message_hash(source), execution_user=frappe.session.user, flow_run=run.name,
            generation=int(contact.automation_generation or 0), ticket=admission.ticket,
            ownership_generation=admission.ownership_generation, status='Pending'))
        select_skill(child, source, node['ai_skill'])
        internal_save(child, new=True)
        name = child.name
    child = frappe.get_doc('Relay Automation Run', name)
    if child.status in ('Completed', 'Shadow'):
        # SEARCH needs a customer confirmation; it owns the next turn.
        if child.get('search_plan') and child.stage == 'Search':
            run.status = 'Completed';internal_save(run);finish(event)
            return False
        return True
    if child.status in ('Handoff', 'Cancelled'):
        run.status = child.status;run.reason = child.reason
        internal_save(run);finish(event)
        return False
    frappe.enqueue('relay_core.automation.service.process', name=name, queue=QUEUE, enqueue_after_commit=True)
    event.next_attempt = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=15)
    internal_save(event);frappe.db.commit()
    return False


def missing_actions(nodes):
    from relay_core.flows.actions import definitions
    registered=definitions(context='flow')
    return sorted({node['action'] for node in nodes if node['kind']=='action' and node['action'] not in registered})


def keywords(value):
    """Whole-message keywords, one per line or comma separated, compared without case."""
    if value in (None,''):return []
    if not isinstance(value,str) or len(value)>2000:frappe.throw('Keywords must contain at most 2,000 characters')
    result=[]
    for word in re.split(r'[\n,]',value):
        word=' '.join(word.split())
        if not word:continue
        if len(word)>60:frappe.throw('Each keyword must contain at most 60 characters')
        if word.casefold() not in (item.casefold() for item in result):result.append(word)
    if len(result)>20:frappe.throw('Choose at most 20 keywords')
    return result


def check_keywords(doc):
    """Two enabled flows on one channel cannot claim the same keyword."""
    if not doc.enabled or not doc.keywords:return
    mine={word.casefold() for word in keywords(doc.keywords)}
    others=frappe.get_all('Relay Flow',filters={'channel':doc.channel,'enabled':1,'name':['!=',doc.name or ''],'keywords':['is','set']},
        fields=['title','keywords'],limit_page_length=0)
    for row in others:
        clash=mine & {word.casefold() for word in keywords(row.keywords)}
        if clash:frappe.throw('Keyword {} already starts the flow {}'.format(sorted(clash)[0],row.title))


def keyword_map():
    """Enabled keywords per channel, cached until a flow changes."""
    def build():
        result={}
        for row in frappe.get_all('Relay Flow',filters={'enabled':1,'keywords':['is','set']},fields=['name','channel','keywords'],limit_page_length=0):
            for word in keywords(row.keywords):result.setdefault(row.channel,{})[word.casefold()]=row.name
        return result
    return frappe.cache.get_value(KEYWORD_CACHE,generator=build)


def clear_keywords(doc=None,method=None):
    frappe.cache.delete_value(KEYWORD_CACHE)


@frappe.whitelist(methods=['GET'])
def directory(after=None,query=''):
    require_access(manage=True)
    features.require('flows')
    if not isinstance(query,str) or len(query)>80:
        frappe.throw('Invalid flow search')
    filters={'name':['>',after]} if after else {}
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=frappe.get_list('Relay Flow',filters=filters,
        or_filters=[['title','like',needle],['command','like',needle],['keywords','like',needle],['legacy_key','like',needle]],
        fields=['name','title','command','keywords','template_button','channel','enabled','published_version','legacy_key','modified'],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None,
            'can_configure':can_manage()}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access(manage=True)
    features.require('flows')
    doc=frappe.get_doc('Relay Flow',name);doc.check_permission('read')
    result={key:doc.get(key) for key in ('name','title','command','keywords','channel','execution_user','business_doctype','enabled','nodes','published_version','template_button','legacy_key')}
    result['published_nodes']=None
    result['missing_actions']=missing_actions(definition(doc.nodes))
    if doc.published_version:
        version=frappe.get_doc('Relay Flow Version',doc.published_version)
        if version.flow!=doc.name:frappe.throw('Published workflow version is invalid')
        result['published_nodes']=version.nodes
        result['published_settings']={key:version.get(key) for key in ('channel','execution_user','business_doctype','command','keywords','template_button')}
    return result


@frappe.whitelist(methods=['GET'])
def providers(query='',after=None):
    """Return enabled AI Models with enabled provider accounts."""
    require_access(manage=True)
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
    """Search runtime values accepted by flow validation."""
    require_access(manage=True)
    if not isinstance(query,str) or len(query)>80:
        frappe.throw('Invalid reference search')
    if kind=='channel':
        needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        rows=frappe.get_list('Relay Channel',filters={'enabled':1},
            or_filters=[['name','like',needle],['account','like',needle]],
            fields=['name','account'],order_by='name asc',page_length=30)
        return [{'value':row.name,'label':' · '.join(filter(None,(row.name,row.account)))} for row in rows]
    if kind in ('ai_skill','team','user'):
        from relay_core.automation.channel import references as channel_references
        return channel_references(kind,query)
    if kind not in ('execution_user','business_doctype'):
        frappe.throw('Invalid flow reference')
    from relay_core.automation.settings import reference_options
    return reference_options(kind,query)


@frappe.whitelist(methods=['POST'])
def save(values,name=None):
    require_access(manage=True)
    features.require('flows')
    if isinstance(values,str):values=frappe.parse_json(values)
    if not isinstance(values,dict) or set(values)-FLOW_FIELDS:frappe.throw('Invalid flow fields')
    if 'nodes' in values:values=dict(values,nodes=json.dumps(definition(values['nodes'])))
    doc=frappe.get_doc('Relay Flow',name) if name else frappe.new_doc('Relay Flow')
    doc.update(values);doc.save()
    return read(doc.name)


@frappe.whitelist(methods=['POST'])
def validate_draft(values,name=None):
    """Validate a complete AI-authored draft without writing it."""
    require_access(manage=True)
    if isinstance(values,str):values=frappe.parse_json(values)
    if not isinstance(values,dict) or set(values)-FLOW_FIELDS:frappe.throw('Invalid flow fields')
    doc=frappe.get_doc('Relay Flow',name) if name else frappe.new_doc('Relay Flow')
    doc.update(values)
    validate_flow(doc)
    return {
        'valid':True,
        'name':doc.name if name else None,
        'title':doc.title,
        'command':doc.command,
        'keywords':doc.keywords,
        'channel':doc.channel,
        'execution_user':doc.execution_user,
        'business_doctype':doc.business_doctype,
        'enabled':int(doc.enabled or 0),
        'nodes':definition(doc.nodes),
        'template_button':doc.get('template_button') or '',
    }


@frappe.whitelist(methods=['POST'])
def publish(name):
    require_access(manage=True)
    features.require('flows')
    with frappe.cache.lock('relay-flow-publish-'+name,timeout=15,blocking_timeout=3):
        doc=frappe.get_doc('Relay Flow',name);doc.check_permission('write')
        validate_compatibility(doc, definition(doc.nodes))
        data={key:doc.get(key) for key in ('nodes','channel','execution_user','business_doctype','template_button','command','keywords')}
        version=frappe.get_doc({'doctype':'Relay Flow Version','flow':doc.name,**data,
                              'definition_hash':digest(json.dumps(data,sort_keys=True))})
        internal_save(version,new=True);doc.published_version=version.name
        internal_save(doc);frappe.db.commit()
    return read(name)


@frappe.whitelist(methods=['POST'])
def set_enabled(name,enabled):
    """Enable or disable a published flow through an explicit MCP-safe action."""
    require_access(manage=True)
    features.require('flows')
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
    if context.get('provider') not in ('WhatsApp','Telegram','Email'):return None
    if context.get('provider')=='WhatsApp' and context.get('original_message_type')=='button':
        data=message.get('message_data') or {}
        if isinstance(data,str):data=json.loads(data)
        payload=data.get('selection_id') if isinstance(data,dict) and data.get('selection_type')=='template_button' else None
        if isinstance(payload,str) and payload:
            return frappe.db.get_value('Relay Flow',{'button_key':digest(message.channel,payload),'enabled':1},'name')
    command=(message.content or '').strip()
    first=(command.split() or [''])[0]
    if re.fullmatch(COMMAND,first):
        return frappe.db.get_value('Relay Flow',{'trigger_key':digest(message.channel,first),'enabled':1},'name')
    return keyword_map().get(message.channel,{}).get(' '.join(command.split()).casefold())


def active(key):
    """The conversation's open run. A run left unanswered for a week no longer captures replies."""
    since=frappe.utils.add_to_date(frappe.utils.now_datetime(),days=-RUN_DAYS)
    return frappe.db.get_value('Relay Flow Run',{'conversation_key':key,'status':['in',['Running','Waiting']],
        'creation':['>',since]},'name',order_by='name desc')


def claims(message):
    """A text can start a flow; any reply a step accepts (text, media, location, contact) continues one."""
    if message.get('legacy_source') or message.direction!='Incoming' or message.message_type not in CLAIMED_TYPES:
        return False
    if not features.is_enabled('flows'):
        return False
    try:
        context=context_of(message)
    except (ValueError,TypeError):
        return False
    if context.get('provider') not in ('WhatsApp','Telegram','Email') or context.get('group_id'):return False
    if message.message_type in ('',None,'text') and matching(message):
        return True
    key=route(message)
    return bool(active(key) or frappe.db.exists('Relay Flow Event', {'conversation_key': key, 'status': 'Pending'}))


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
    if not flow.enabled or version.flow!=flow.name:
        raise ValueError('Flow was disabled or version is invalid')
    check_actor(version)
    frappe.set_user(version.execution_user)
    from relay_core.messaging import readable_source
    source,channel,context=readable_source(message.name)
    from relay_core.automation.channel import enabled
    if not enabled(channel):
        raise ValueError('Channel automation is disabled')
    if channel.channel not in ('WhatsApp','Telegram','Email') or context.get('provider')!=channel.channel or context.get('group_id'):
        raise ValueError('Flow channel is unavailable')
    if source.direction!='Incoming' or channel.name!=version.channel or route(source)!=run.conversation_key:
        raise ValueError('Flow conversation changed')
    contact,_=readable_contact(source.relay_contact)
    if source.get('ticket'):
        from relay_core.tickets import check_episode
        from relay_core.automation.contracts import event_key
        admission = frappe.db.get_value('Relay Automation Run', {'event_key': event_key(run.start_message)},
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


def send(run,event,source,channel,text,key,choices=None):
    from relay_core.messaging import send as message_send, outgoing_flow
    marker = {'name': run.name, 'version': run.version, 'generation': int(run.generation or 0)}
    if run.status == 'Handoff': marker['handoff'] = True
    token = outgoing_flow.set(marker)
    try:
        if channel.channel=='Email':
            from relay_core.email import send as email_send
            result=email_send([source.sender_endpoint],'Flow update',text,message=source.name,request_key=key,auto_submitted=1)
        else:
            result=message_send(source.name,'choices' if choices else 'text',choices or {'text':text},key)
    finally:
        outgoing_flow.reset(token)
    if result.get('status')!='Submitted':raise RuntimeError('Delivery not confirmed')


def flow_ticket(source, text):
    from relay_core.tickets import ensure_episode, _save_episode
    actor = frappe.session.user
    try:
        frappe.set_user('Administrator')
        ticket = ensure_episode(source, owner=actor, subject=text[:140] or 'Conversation needs a person', reason=text)
        ticket.subject, ticket.brief = text[:140] or 'Conversation needs a person', text[:500]
        _save_episode(ticket)
        return ticket
    finally:
        frappe.set_user(actor)


class StepLimit(ValueError):
    pass


def next_step(nodes,index):
    target=nodes[index].get('next')
    return next(i for i,node in enumerate(nodes) if node['id']==target) if target else index+1


def visit(run,nodes,values,index):
    """Move the run to a step and count the visit; a loop stops at the step's repeat limit."""
    run.step=index
    if index<len(nodes):
        node=nodes[index];visits=values.setdefault('_visits',{})
        visits[node['id']]=visits.get(node['id'],0)+1
        if visits[node['id']]>node.get('max_visits',DEFAULT_VISITS):
            raise StepLimit('Step '+node['id']+' repeated more than '+str(node.get('max_visits',DEFAULT_VISITS))+' times')
    run.values=json.dumps(values)


def step_key(run,node,values):
    """Stable per visit, so a retry reuses its delivery and action keys but a loop gets new ones."""
    count=values.get('_visits',{}).get(node['id'],1)
    return 'flow-'+run.name+'-'+node['id']+('-'+str(count) if count>1 else '')


def finish(event):
    event.status='Complete';event.reason='';internal_save(event);frappe.db.commit()


def _process(event):
    message=frappe.get_doc('Relay Message',event.message)
    if message_hash(message)!=event.message_hash:raise ValueError('Input changed after it was queued')
    if event.run:
        run=frappe.get_doc('Relay Flow Run',event.run)
    else:
        current=active(event.conversation_key)
        flow_name=None if current else matching(message)
        if flow_name:
            flow=frappe.get_doc('Relay Flow',flow_name)
            contact=frappe.get_doc('Relay Contact',message.relay_contact)
            from relay_core.business_access import reference
            target=reference(message)
            if not target:raise ValueError('Flow business context is missing or ambiguous')
            run=frappe.get_doc({'doctype':'Relay Flow Run','flow':flow_name,'version':flow.published_version,
                'conversation_key':event.conversation_key,'start_message':message.name,'last_message':message.name,
                'relay_contact':message.relay_contact,'business_doctype':target[0],'business_name':target[1],
                'generation':contact.automation_generation or 0,
                'status':'Running','step':0})
            visit(run,definition(frappe.db.get_value('Relay Flow Version',flow.published_version,'nodes')),{},0)
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
    if run.status=='Waiting' and not event.input_applied and (message.content or '').strip().casefold() in EXIT_WORDS:
        send(run,event,source,channel,'The current flow has been closed.',step_key(run,{'id':'exit'},values))
        run.status='Cancelled';run.reason='Closed by the customer';internal_save(run);finish(event);return
    if run.status=='Waiting' and not event.input_applied:
        node=nodes[run.step]
        try:value=parse_input(node,input_value(message,node),{'message_type':message.message_type,'name':message.name})
        except ValueError as error:
            text=node.get('error_text') or str(error)+'\n'+prompt(node,values)
            send(run,event,source,channel,text,'flow-'+event.name+'-invalid')
            finish(event);return
        values[node['variable']]=values[LAST_INPUT]=value
        visit(run,nodes,values,next_step(nodes,run.step));run.status='Running';run.last_message=message.name
        event.input_applied=1;internal_save(run);internal_save(event);frappe.db.commit()
    elif run.status=='Waiting':
        finish(event);return
    # Bound one job to five side effects. Remaining steps resume from persisted state.
    for _ in range(5):
        if run.step>=len(nodes):
            run.status='Completed';internal_save(run);finish(event);return
        version,source,channel=scope(run,message)
        node=nodes[run.step];text=render(node['text'],values);key=step_key(run,node,values)
        if node['kind']=='end':
            if text.strip():send(run,event,source,channel,text,key+'-end')
            run.status='Completed';internal_save(run);finish(event);return
        if node['kind']=='condition':
            target=node['then'] if matches(node,values) else node['otherwise']
            visit(run,nodes,values,next(index for index,item in enumerate(nodes) if item['id']==target))
            internal_save(run);frappe.db.commit();continue
        if node['kind']=='wait':
            visit(run,nodes,values,next_step(nodes,run.step))
            event.next_attempt=frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=node['seconds'])
            run.reason='Waiting until '+str(event.next_attempt);internal_save(run)
            internal_save(event);frappe.db.commit();return
        if node['kind']=='input':
            send_prompt(run,event,source,channel,node,values,key+'-prompt');run.status='Waiting';internal_save(run);finish(event);return
        if node['kind']=='reply':
            send(run,event,source,channel,text,key)
        elif node['kind']=='ticket':
            flow_ticket(source, text)
        elif node['kind']=='assign':
            from relay_core.automation.channel import assign_conversation
            assign_conversation(source.relay_contact, node.get('team'), node.get('user'))
        elif node['kind']=='ai_skill':
            if not run_skill(run,event,source,node,key):return
            if node.get('on_reply','Continue')=='Stop':
                run.status='Completed';internal_save(run);finish(event);return
        elif node['kind']=='action':
            from relay_core.flows.actions import execute
            result=execute(run,node,values,key)
            if node.get('variable'):values[node['variable']]=result
        elif node['kind']=='topic':
            from relay_core.topics import upsert
            sources=frappe.get_all('Relay Flow Event',filters={'run':run.name,'input_applied':1},pluck='message',order_by='name asc',limit_page_length=501)
            if len(sources)>500:raise ValueError('Topic contains too many messages')
            upsert(run.relay_contact,{'title':render(node['title'],values)[:140],
                'summary':text,'category':node.get('category',''),'status':node.get('status','Open'),
                'messages':list(dict.fromkeys([run.start_message]+sources))},source='Flow',source_key=key)
        elif node['kind']=='handoff':
            if text.strip():send(run,event,source,channel,text,key+'-handoff')
            ticket = flow_ticket(source, text)
            from relay_core.tickets import hold_episode
            hold_episode(ticket.name)
            run.status='Handoff';internal_save(run);finish(event)
            return
        visit(run,nodes,values,next_step(nodes,run.step));internal_save(run);frappe.db.commit()
    frappe.enqueue('relay_core.flows.service.process',name=event.name,queue=QUEUE,enqueue_after_commit=True)


def process(name):
    actor=frappe.session.user
    event=frappe.get_doc('Relay Flow Event',name)
    with frappe.cache.lock('relay-flow-conversation-'+event.conversation_key,timeout=300,blocking_timeout=1):
        event.reload()
        if event.status!='Pending':return
        if not features.is_enabled('flows'):
            event.status='Rejected';event.reason='Flows are turned off';internal_save(event);frappe.db.commit();return
        if event.next_attempt and frappe.utils.get_datetime(event.next_attempt)>frappe.utils.now_datetime():return
        first=None
        pending=frappe.get_all('Relay Flow Event',filters={'conversation_key':event.conversation_key,'status':'Pending'},fields=['name','run'],order_by='name asc',limit_page_length=100)
        for item in pending:
            if item.run and frappe.db.get_value('Relay Flow Run',item.run,'status') not in ('Running','Waiting'):
                finished=frappe.get_doc('Relay Flow Event',item.name);finish(finished)
                continue
            first=item.name;break
        if first!=event.name:return
        try:_process(event)
        except (frappe.PermissionError,frappe.ValidationError,ValueError) as error:
            frappe.db.rollback();event.reload()
            if event.status == 'Complete': return
            event.status='Rejected'
            event.reason=str(error) if isinstance(error,StepLimit) else 'Flow, input or conversation is no longer permitted'
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
        finally:
            frappe.set_user(actor)
            wake_next(event)


def wake_next(event):
    """A reply that arrived while this one ran waits in order; start it now instead of at the next recovery pass."""
    if event.status=='Pending':return
    following=frappe.db.get_value('Relay Flow Event',{'conversation_key':event.conversation_key,'status':'Pending'},'name',order_by='name asc')
    if following:
        frappe.enqueue('relay_core.flows.service.process',name=following,queue=QUEUE,job_id='relay-flow-'+following,deduplicate=True)


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
    features.require('flows')
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
    require_access(manage=True)
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
