"""Internal discussion. Every read/write rechecks the linked conversation."""
import hashlib
import json
import re
import frappe
from relay_core.business_access import document_name
from relay_core.permissions import require_access, readable_contact, can_manage
from relay_core.api import validate_reference


def save(doc):
    previous = getattr(frappe.flags, 'relay_collaboration_write', False)
    frappe.flags.relay_collaboration_write = True
    try:
        doc.messages = json.dumps(frappe.parse_json(doc.messages) or [])
        doc.mentions = json.dumps(frappe.parse_json(doc.mentions) or [])
        result=doc.save(ignore_permissions=True)
        from relay_core.realtime import contact_changed
        contact_changed(doc.relay_contact,'comments')
        return result
    finally:
        frappe.flags.relay_collaboration_write = previous


def references(contact, values):
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v,str) for v in values) or len(values) != len(set(values)):
        frappe.throw('Select at most 20 distinct messages')
    for name in values:
        validate_reference(name, 'MSG')
        message = frappe.get_doc('Relay Message', name)
        message.check_permission('read')
        frappe.get_doc('Relay Channel', message.channel).check_permission('read')
        if message.relay_contact != contact:
            frappe.throw('Message belongs to another conversation', frappe.PermissionError)
    return values


def business_scope(contact, messages, doctype=None, name=None):
    """The note's business. A contact without business links keeps notes on the conversation itself.
    Linked content requires access to its business type."""
    from relay_core.business_access import choose_business, reference, unlinked_contact
    targets = {reference(frappe.get_doc('Relay Message', value)) for value in messages}
    if targets:
        if len(targets) != 1:
            frappe.throw('Choose messages from one business', frappe.PermissionError)
        target = targets.pop()
        if (doctype or name) and target != (doctype, name):
            frappe.throw('Messages belong to another business', frappe.PermissionError)
        if target:
            doctype, name = target
    if not (doctype or name) and unlinked_contact(contact):
        return None, None
    return choose_business(contact, doctype, name)


def authorize(doc, user=None):
    """A note follows its conversation's read rule, like the conversation's messages."""
    from relay_core.business_access import reference, business_document, unlinked_contact
    names = frappe.parse_json(doc.messages) or []
    if not doc.get('business_name') and names:
        targets = {reference(frappe.get_doc('Relay Message', name)) for name in names}
        if len(targets) == 1 and None not in targets:
            doc.business_doctype, doc.business_name = targets.pop()
    conversation_reader(doc.relay_contact, user)
    if not doc.get('business_name'):
        target = reference(doc)
        if target:
            doc.business_doctype, doc.business_name = target
    if doc.get('business_doctype') or doc.get('business_name'):
        business_document(doc.get('business_doctype'), doc.get('business_name'), user)
    elif not unlinked_contact(doc.relay_contact):
        frappe.throw('Choose an accessible business for this comment', frappe.PermissionError)
    for name in names:
        message = frappe.get_doc('Relay Message', name)
        if message.relay_contact != doc.relay_contact or not message.has_permission('read', user=user):
            frappe.throw('Comment evidence is not accessible', frappe.PermissionError)
        if not frappe.get_doc('Relay Channel', message.channel).has_permission('read', user=user):
            frappe.throw('Comment channel is not accessible', frappe.PermissionError)
    return doc


def conversation_reader(contact, user=None):
    from relay_core.permissions import can_read_contact_as
    if user is None:
        readable_contact(contact)
    elif not can_read_contact_as(contact, user):
        frappe.throw('Conversation is not accessible', frappe.PermissionError)


def editable(doc):
    return doc.owner == frappe.session.user or can_manage()


def serialize(doc):
    authorize(doc)
    values = [] if doc.deleted else references(doc.relay_contact, doc.messages or [])
    return {'name':doc.name,'body':'' if doc.deleted else doc.body,'deleted':bool(doc.deleted),
            'author':doc.owner,'author_name':frappe.db.get_value('User',doc.owner,'full_name') or doc.owner,
            'creation':doc.creation,'modified':doc.modified,'messages':values,'reply_to':doc.reply_to,
            'can_edit':not doc.deleted and editable(doc),'assigned_to':doc.assigned_to,'task_status':doc.task_status,
            'can_complete':not doc.deleted and bool(doc.assigned_to) and (editable(doc) or doc.assigned_to==frappe.session.user),
            'mentions':frappe.parse_json(doc.mentions) or []}


@frappe.whitelist(methods=['GET'])
def comments(contact, before=None):
    require_access(); readable_contact(contact)
    filters={'relay_contact':contact}
    if before:
        if not isinstance(before,str) or not re.fullmatch(r'RELAY-NOTE-[0-9]{10}',before):
            frappe.throw('Invalid comment cursor')
        filters['name']=['<',before]
    rows=frappe.get_all('Relay Internal Comment',filters=filters,fields=['name'],order_by='name desc',limit_page_length=31)
    items=[]
    for row in reversed(rows[:30]):
        try: items.append(serialize(frappe.get_doc('Relay Internal Comment', row.name)))
        except frappe.PermissionError: continue
    return {'items':items,
            'more':len(rows)>30,'before':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['POST'])
def add(contact, body, request_key, messages=None, reply_to=None, assigned_to=None, mentions=None, business_doctype=None, business_name=None):
    if reply_to is not None and reply_to != "":
        document_name(reply_to)
    require_access(); readable_contact(contact)
    if not isinstance(body,str) or not 1<=len(body.strip())<=4000:
        frappe.throw('Comment must contain 1–4000 characters')
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',request_key):
        frappe.throw('Invalid comment request key')
    values=references(contact,messages or [])
    parent = authorize(frappe.get_doc('Relay Internal Comment', reply_to)) if reply_to else None
    if parent and not (business_doctype or business_name):
        business_doctype, business_name = parent.business_doctype, parent.business_name
    business = business_scope(contact, values, business_doctype, business_name)
    scope = frappe._dict(relay_contact=contact, messages=values, business_doctype=business[0], business_name=business[1])
    mentions=recipients(contact,mentions or [], scope)
    assigned_to=assigned_to or None
    if assigned_to:recipients(contact,[assigned_to], scope)
    if reply_to:
        if (parent.business_doctype, parent.business_name) != business:
            frappe.throw('Reply belongs to another business', frappe.PermissionError)
        if parent.relay_contact!=contact or parent.deleted:
            frappe.throw('Reply belongs to another conversation or was removed',frappe.PermissionError)
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    with frappe.cache.lock('relay-comment-'+key,timeout=10,blocking_timeout=3):
        existing=frappe.db.get_value('Relay Internal Comment',{'request_key':key},'name')
        if existing:
            doc=frappe.get_doc('Relay Internal Comment',existing)
            if (doc.business_doctype, doc.business_name)!=business or doc.relay_contact!=contact or doc.body!=body.strip() or (frappe.parse_json(doc.messages) or [])!=values or (doc.reply_to or '')!=(reply_to or '') or (doc.assigned_to or None)!=assigned_to or (frappe.parse_json(doc.mentions) or [])!=mentions:
                frappe.throw('Comment request key was already used')
        else:
            doc=frappe.get_doc({'doctype':'Relay Internal Comment','relay_contact':contact,'body':body.strip(),
                                'business_doctype':business[0],'business_name':business[1],
                                'messages':json.dumps(values),'reply_to':reply_to,'request_key':key,'assigned_to':assigned_to,
                                'task_status':'Open' if assigned_to else None,'mentions':json.dumps(mentions)})
            save(doc);notify(doc);frappe.db.commit()
    return serialize(doc)


@frappe.whitelist(methods=['POST'])
def edit(name, body=None, remove=0):
    document_name(name)
    require_access()
    if str(remove) not in ('0','1','False','True'):frappe.throw('Invalid removal flag')
    frappe.db.get_value('Relay Internal Comment',name,'name',for_update=True)
    doc=authorize(frappe.get_doc('Relay Internal Comment',name))
    if not editable(doc):frappe.throw('Only the author or a manager can edit this comment',frappe.PermissionError)
    if doc.deleted:frappe.throw('Comment was already removed')
    if str(remove) in ('1','True'):doc.deleted=1
    else:
        if not isinstance(body,str) or not 1<=len(body.strip())<=4000:frappe.throw('Comment must contain 1–4000 characters')
        doc.body=body.strip()
    save(doc)
    return serialize(doc)


def recipients(contact,values,doc=None):
    from relay_core.permissions import can_read_contact_as
    values=frappe.parse_json(values) if isinstance(values,str) else values
    if not isinstance(values,list) or len(values)>10 or any(not isinstance(user,str) for user in values) or len(values)!=len(set(values)):
        frappe.throw('Choose at most 10 distinct colleagues')
    if any(not can_read_contact_as(contact,user) for user in values):frappe.throw('A selected colleague cannot access this conversation',frappe.PermissionError)
    if doc:
        for user in values: authorize(doc, user)
    return values


@frappe.whitelist(methods=['GET'])
def colleagues(contact,query=''):
    require_access();readable_contact(contact)
    from relay_core.permissions import can_read_contact_as
    from relay_core.teams import _agent_options
    if not isinstance(query,str) or len(query)>80:frappe.throw('Invalid colleague search')
    query=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    rows=_agent_options(query,contact=contact)
    return [dict(value=row.name,label=row.full_name or row.name) for row in rows if can_read_contact_as(contact,row.name)]



def notify(doc):
    from relay_core.permissions import can_read_contact_as
    targets={user:'Mention' for user in frappe.parse_json(doc.mentions) or []}
    if doc.reply_to:
        author=frappe.db.get_value('Relay Internal Comment',doc.reply_to,'owner')
        if author:targets.setdefault(author,'Reply')
    if doc.assigned_to:targets[doc.assigned_to]='Task'
    previous=getattr(frappe.flags,'relay_collaboration_write',False);frappe.flags.relay_collaboration_write=True
    try:
        for user,kind in targets.items():
            if user==frappe.session.user or not can_read_contact_as(doc.relay_contact,user):continue
            try: authorize(doc, user)
            except frappe.PermissionError: continue
            key=hashlib.sha256((doc.name+':'+user).encode()).hexdigest()
            if not frappe.db.exists('Relay Notification',{'event_key':key}):
                frappe.get_doc(dict(doctype='Relay Notification',user=user,relay_contact=doc.relay_contact,comment=doc.name,kind=kind,event_key=key)).insert(ignore_permissions=True)
    finally:frappe.flags.relay_collaboration_write=previous


@frappe.whitelist(methods=['POST'])
def task_status(name,status):
    document_name(name)
    require_access()
    if status not in ('Open','Done'):frappe.throw('Invalid task status')
    frappe.db.get_value('Relay Internal Comment',name,'name',for_update=True)
    doc=authorize(frappe.get_doc('Relay Internal Comment',name))
    if doc.deleted or not doc.assigned_to or not (editable(doc) or doc.assigned_to==frappe.session.user):
        frappe.throw('Only the task owner, author or manager can change this task',frappe.PermissionError)
    doc.task_status=status;save(doc)
    return serialize(doc)


@frappe.whitelist(methods=['GET'])
def notifications(before=None):
    require_access()
    filters={'user':frappe.session.user}
    if before:
        if not isinstance(before,str) or not re.fullmatch(r'RELAY-NOTIFY-[0-9]{10}',before):frappe.throw('Invalid notification cursor')
        filters['name']=['<',before]
    rows=frappe.get_all('Relay Notification',filters=filters,fields=['name','relay_contact','comment','kind','is_read','creation'],order_by='name desc',limit_page_length=31)
    items=[]
    for row in rows[:30]:
        try:readable_contact(row.relay_contact)
        except frappe.PermissionError:continue
        doc=frappe.get_doc('Relay Internal Comment',row.comment)
        if doc.deleted:continue
        try: value=serialize(doc)
        except frappe.PermissionError: continue
        items.append(dict(row,contact_name=frappe.db.get_value('Relay Contact',row.relay_contact,'display_name'),body=value['body'][:180]))
    return {'items':items,'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['POST'])
def mark_notification(name):
    document_name(name)
    require_access();doc=frappe.get_doc('Relay Notification',name)
    if doc.user!=frappe.session.user:frappe.throw('Notification belongs to another user',frappe.PermissionError)
    frappe.db.set_value('Relay Notification',doc.name,'is_read',1)
    return {'read':True}
