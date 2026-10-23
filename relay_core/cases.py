"""Scoped operational cases pinned to the lifecycle used when they were created."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.case_contracts import lifecycle, transition


def validate_type(doc):
    require_access(configure=True)
    if not isinstance(doc.title, str) or not 1 <= len(doc.title.strip()) <= 140:
        frappe.throw('Enter a case type title of 1–140 characters')
    if not isinstance(doc.type_key, str) or not 1 <= len(doc.type_key) <= 140:
        frappe.throw('Enter a stable case type key')
    doc.definition = json.dumps(lifecycle(doc.definition))


def _read(doc):
    readable_contact(doc.relay_contact)
    return {**{k:doc.get(k) for k in ('name','title','case_type','relay_contact','priority','stage','state','modified','closed_at','assigned_to')},
            'can_assign':bool(set(frappe.get_roles()).intersection({'System Manager','Relay Communication Manager'})),
            'field_values':json.loads(doc.field_values),'definition':json.loads(doc.definition)}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access()
    return _read(frappe.get_doc('Relay Case',name))


def create(case_type, contact, title, field_values, request_key, source_flow=None):
    require_access();readable_contact(contact)
    if not isinstance(title,str) or not 1<=len(title.strip())<=140:
        frappe.throw('Enter a case title of 1–140 characters')
    if not isinstance(request_key,str) or not 1<=len(request_key)<=500:
        frappe.throw('A stable case request key is required')
    intent=hashlib.sha256(json.dumps([case_type,contact,title.strip(),field_values,source_flow],sort_keys=True,allow_nan=False).encode()).hexdigest()
    key=hashlib.sha256(json.dumps([case_type,contact,request_key]).encode()).hexdigest()
    with frappe.cache.lock('relay-case-'+key,timeout=30,blocking_timeout=3):
        previous=frappe.db.get_value('Relay Case',{'request_key':key},'name')
        if previous:
            if frappe.db.get_value('Relay Case',previous,'intent_hash')!=intent:frappe.throw('Case request changed after creation')
            return read(previous)
        kind=frappe.get_doc('Relay Case Type',case_type)
        if not kind.enabled:frappe.throw('Case type is disabled')
        definition=lifecycle(kind.definition)
        values,state=transition(definition,definition['initial_stage'],field_values)
        if source_flow and frappe.db.get_value('Relay Flow Run',source_flow,'relay_contact')!=contact:
            frappe.throw('Flow belongs to another contact',frappe.PermissionError)
        doc=frappe.get_doc({'doctype':'Relay Case','request_key':key,'case_type':case_type,'relay_contact':contact,
            'title':title.strip(),'priority':definition.get('priority','Normal'),'stage':definition['initial_stage'],
            'intent_hash':intent,'closed_at':frappe.utils.now_datetime() if state in ('done','cancelled') else None,
            'state':state,'definition':json.dumps(definition),'field_values':json.dumps(values),'source_flow':source_flow})
        doc.insert(ignore_permissions=True);frappe.db.commit()
        return _read(doc)


@frappe.whitelist(methods=['POST'])
def move(name, stage, values, modified):
    require_access()
    if isinstance(values,str):values=frappe.parse_json(values)
    if not isinstance(values,dict):frappe.throw('Case fields must be an object')
    with frappe.cache.lock('relay-case-edit-'+hashlib.sha256(name.encode()).hexdigest(),timeout=30,blocking_timeout=3):
        doc=frappe.get_doc('Relay Case',name);readable_contact(doc.relay_contact)
        if str(doc.modified)!=str(modified):frappe.throw('This case changed. Reload before saving.')
        merged={**json.loads(doc.field_values),**values}
        fields,state=transition(doc.definition,stage,merged,doc.stage)
        doc.stage=stage;doc.state=state;doc.field_values=json.dumps(fields)
        doc.closed_at=(doc.closed_at or frappe.utils.now_datetime()) if state in ('done','cancelled') else None
        doc.save(ignore_permissions=True);frappe.db.commit()
        return _read(doc)


@frappe.whitelist(methods=['GET'])
def directory(contact, after=None):
    require_access();readable_contact(contact)
    filters={'relay_contact':contact}
    if after:filters['name']=['<',after]
    rows=frappe.get_all('Relay Case',filters=filters,fields=['name','title','priority','stage','state','modified'],order_by='name desc',limit_page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def workspace(query='', state=None, after=None):
    """Bounded keyset scan; unreadable contacts never enter the result payload."""
    require_access()
    if not isinstance(query,str) or len(query)>80:frappe.throw('Case search must contain at most 80 characters')
    if state and state not in ('open','active','waiting','done','cancelled'):frappe.throw('Unsupported case state')
    filters={}
    if state:filters['state']=state
    if after:filters['name']=['<',after]
    if query:filters['title']=['like','%'+query.replace('%','\\%').replace('_','\\_')+'%']
    rows=frappe.get_all('Relay Case',filters=filters,fields=['name','title','relay_contact','priority','stage','state','modified'],order_by='name desc',limit_page_length=51)
    items=[];permissions={}
    for row in rows[:50]:
        if row.relay_contact not in permissions:
            try:readable_contact(row.relay_contact);permissions[row.relay_contact]=True
            except frappe.PermissionError:permissions[row.relay_contact]=False
        if permissions[row.relay_contact]:items.append(row)
    return {'items':items,'next':rows[49].name if len(rows)>50 else None}


@frappe.whitelist(methods=['GET'])
def types(contact):
    require_access();readable_contact(contact)
    rows=frappe.get_all('Relay Case Type',filters={'enabled':1},fields=['name','title','definition'],order_by='title asc',limit_page_length=100)
    return [{'name':row.name,'title':row.title,'definition':lifecycle(row.definition)} for row in rows]


@frappe.whitelist(methods=['POST'])
def create_manual(case_type, contact, title, field_values, request_key):
    require_access();readable_contact(contact)
    if not isinstance(request_key,str) or not 1<=len(request_key)<=140:frappe.throw('A case request key is required')
    if isinstance(field_values,str):field_values=frappe.parse_json(field_values)
    return create(case_type,contact,title,field_values,'manual:'+frappe.session.user+':'+str(request_key))


@frappe.whitelist(methods=['POST'])
def assign(name, user, modified):
    require_access(manage=True)
    from relay_core.permissions import can_read_contact_as
    if not isinstance(user,str):frappe.throw('Choose an agent')
    with frappe.cache.lock('relay-case-edit-'+hashlib.sha256(name.encode()).hexdigest(),timeout=30,blocking_timeout=3):
        doc=frappe.get_doc('Relay Case',name);readable_contact(doc.relay_contact)
        if str(doc.modified)!=str(modified):frappe.throw('This case changed. Reload before assigning.')
        if user and not can_read_contact_as(doc.relay_contact,user):frappe.throw('Agent cannot access this conversation',frappe.PermissionError)
        doc.assigned_to=user or None;doc.save(ignore_permissions=True);frappe.db.commit()
        return _read(doc)


@frappe.whitelist(methods=['GET'])
def agents(name, query=''):
    require_access(manage=True)
    from relay_core.permissions import can_read_contact_as
    from relay_core.teams import _agent_options
    doc=frappe.get_doc('Relay Case',name);readable_contact(doc.relay_contact)
    if not isinstance(query,str) or len(query)>80:frappe.throw('Invalid user search')
    query=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    return [row for row in _agent_options(query,contact=doc.relay_contact) if can_read_contact_as(doc.relay_contact,row['name'])]
