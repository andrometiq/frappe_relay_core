"""Retailer follow-up semantics migrated from the legacy business adapter."""
import json
import frappe
from relay_core import cases
from relay_core.permissions import require_access

TYPES = {'catalogue': ('Catalogue','Normal'), 'callback': ('Callback','High'),
         'stocking_interest': ('Stocking Interest','High'), 'mapping_exception': ('Mapping Exception','High'),
         'complaint': ('Complaint','Critical')}


def case_definition(priority):
    return {'priority':priority,'initial_stage':'open',
        'fields':{'type':'object','properties':{key:{'type':'string','title':key.replace('_',' ').title()} for key in
            ('action_type','party','note','completion_evidence')},
            'additionalProperties':{'type':'json'}},
        'stages':[{'key':'open','label':'Open','state':'open'},
            {'key':'in_progress','label':'In Progress','state':'active'},
            {'key':'waiting','label':'Waiting on Party','state':'waiting'},
            {'key':'completed','label':'Completed','state':'done','required_fields':['completion_evidence']},
            {'key':'rejected','label':'Rejected Invalid','state':'cancelled'}]}


def install_case_types():
    """Explicit local setup; never overwrite an administrator's existing definitions."""
    require_access(configure=True)
    result=[]
    for key,(title,priority) in TYPES.items():
        stable='essdee.retailer_connect.'+key
        name=frappe.db.get_value('Relay Case Type',{'type_key':stable},'name')
        if not name:
            doc=frappe.get_doc({'doctype':'Relay Case Type','type_key':stable,'title':title,
                'enabled':1,'definition':json.dumps(case_definition(priority))}).insert()
            name=doc.name
        result.append(name)
    return result


def create_follow_up(*, action_input, relay_contact, business_doctype=None, business_name=None, flow_run, idempotency_key):
    require_access()
    action_type=action_input['action_type']
    if action_type not in ('catalogue','callback','stocking_interest'):
        raise ValueError('Unsupported retailer follow-up type')
    run=frappe.get_doc('Relay Flow Run',flow_run)
    if run.relay_contact!=relay_contact or (run.get('business_doctype'),run.get('business_name'))!=(business_doctype,business_name):
        frappe.throw('Flow belongs to another contact',frappe.PermissionError)
    name=frappe.db.get_value('Relay Case Type',{'type_key':'essdee.retailer_connect.'+action_type},'name')
    if not name:raise ValueError('Install the retailer case types in Desk first')
    existing=frappe.db.get_value('Relay Case',{'case_type':name,'relay_contact':relay_contact,'source_flow':flow_run},'name')
    if existing:
        result=cases.read(existing)
        return {'case':result['name'],'case_type':'essdee.retailer_connect.'+action_type,'stage':result['stage']}
    fields=dict(action_input.get('field_values') or {})
    fields.update(action_type=action_type,note=action_input.get('note',''))
    # Legacy deduplicates each action type across all steps of one flow instance.
    result=cases.create(name,relay_contact,action_input.get('title') or 'Retailer '+action_type.replace('_',' ')+' request',
                        fields,'retailer:'+flow_run+':'+action_type,source_flow=flow_run)
    return {'case':result['name'],'case_type':'essdee.retailer_connect.'+action_type,'stage':result['stage']}


ACTION = {'label':'Create retailer follow-up','method':'relay_core.flows.retailer.create_follow_up','replay_safe':True,
    'description':'Create a catalogue, callback or stocking-interest case using the configured retailer lifecycle.',
    'parameters':{'type':'object','required':['action_type'],'properties':{
        'action_type':{'type':'string','title':'Follow-up type','enum':['catalogue','callback','stocking_interest']},
        'title':{'type':'string','title':'Title','maxLength':140},
        'note':{'type':'string','title':'Note'},
        'field_values':{'type':'object','title':'Collected values','additionalProperties':{'type':'json'}}}}}
