"""Installed automation configuration; API secrets are write-only."""
import re
import frappe
from relay_core.permissions import require_access

PROVIDERS=('OpenAI','OpenRouter','Gemini','Anthropic','GLM')
POLICY_FIELDS=('channel','provider','fallback_provider','execution_user','enabled','mode','allow_ticket','allow_reply','business_doctype','daily_limit','instructions','reply_ids','fallback_reply','allow_images','allow_voice','transcription_provider','allow_report','allow_summary','allow_translation')


@frappe.whitelist(methods=['GET'])
def providers(query='',after=None):
    require_access(configure=True)
    if not isinstance(query,str) or len(query)>80:frappe.throw('Invalid provider search')
    filters={}
    if after:filters['name']=['>',after]
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=frappe.get_list('Relay AI Provider',filters=filters,or_filters=[['model','like',needle],['provider','like',needle]],fields=['name','provider','model','enabled'],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['POST'])
def save_provider(provider,model,enabled=0,api_key='',name=None):
    require_access(configure=True)
    if provider not in PROVIDERS or not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,160}',model):frappe.throw('Choose a supported provider and model identifier')
    if str(enabled) not in ('0','1','True','False'):frappe.throw('Invalid enabled flag')
    if not isinstance(api_key,str) or len(api_key)>1024 or any(ord(c)<32 for c in api_key):frappe.throw('Invalid API key')
    doc=frappe.get_doc('Relay AI Provider',name) if name else frappe.new_doc('Relay AI Provider')
    if name and doc.provider!=provider and not api_key:frappe.throw('Enter a new key when changing providers')
    doc.provider=provider;doc.model=model;doc.enabled=int(str(enabled) in ('1','True'))
    if api_key:doc.api_key=api_key
    doc.save()
    return {'name':doc.name,'provider':doc.provider,'model':doc.model,'enabled':doc.enabled}


@frappe.whitelist(methods=['GET'])
def policies(after=None):
    require_access(configure=True)
    rows=frappe.get_list('Relay Automation Policy',filters={'name':['>',after]} if after else {},fields=['name',*POLICY_FIELDS],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['POST'])
def save_policy(values,name=None):
    require_access(configure=True)
    if isinstance(values,str):values=frappe.parse_json(values)
    if not isinstance(values,dict) or set(values)-set(POLICY_FIELDS):frappe.throw('Invalid policy fields')
    doc=frappe.get_doc('Relay Automation Policy',name) if name else frappe.new_doc('Relay Automation Policy')
    doc.update(values);doc.save()
    return {'name':doc.name}


@frappe.whitelist(methods=['GET'])
def references(kind, query=''):
    """Bounded, permission-checked choices for the installed policy editor."""
    require_access(configure=True)
    choices = {
        'policy': ('Relay Automation Policy', ['name','channel'], {}),
        'source_message': ('Relay Message', ['name'], {'direction':'Incoming'}),
        'channel': ('Relay Channel', ['name', 'channel'], {}),
        'provider': ('Relay AI Provider', ['name', 'provider', 'model'], {}),
        'execution_user': ('User', ['name', 'full_name'], [['User', 'enabled', '=', 1], ['Has Role', 'role', '=', 'Relay Communication Manager']]),
        'reply': ('Relay Canned Reply', ['name', 'language'], {'published': 1, 'ai_enabled': 1}),
    }
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid reference search')
    if kind == 'business_doctype':
        from relay_core.api import business_types
        return [{'value': name, 'label': name} for name in business_types() if query.lower() in name.lower()][:30]
    if kind not in choices or not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid reference search')
    doctype, fields, filters = choices[kind]
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    rows = frappe.get_list(doctype, filters=filters, or_filters=[[field, 'like', pattern] for field in fields],
                           fields=fields, order_by='name asc', page_length=30)
    if kind == 'execution_user':
        rows = [row for row in rows if row.name not in ('Guest', 'Administrator')
                and 'System Manager' not in frappe.get_roles(row.name)
                and 'Relay Communication Manager' in frappe.get_roles(row.name)]
    return [{'value': row.name, 'label': ' · '.join(str(row[field]) for field in fields if row.get(field))} for row in rows]
