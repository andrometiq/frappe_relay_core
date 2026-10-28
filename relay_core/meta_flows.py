"""Manager-only account-scoped Meta Flow lifecycle; credentials stay in Hub."""
import frappe
from relay_core.permissions import require_access
from relay_core.whatsapp import checked_client, connection
from relay_core.hub import HubError
from relay_core.hub_channels import choose, hub_arguments

OPERATIONS={'list','get','json','assets','create','update','upload','publish','deprecate','delete'}
READS={'list','get','json','assets'}

@frappe.whitelist(methods=['GET'])
def workspace():
    require_access(manage=True)
    return connection()

@frappe.whitelist(methods=['POST'])
def execute(operation, arguments=None):
    require_access(manage=True)
    if operation not in OPERATIONS:frappe.throw('Unsupported Meta Flow operation')
    if isinstance(arguments,str):arguments=frappe.parse_json(arguments)
    arguments=arguments or {}
    if not isinstance(arguments,dict) or set(arguments)-{'id','name','categories','endpoint_uri','flow_json','after'}:frappe.throw('Invalid Flow arguments')
    try:
        hub,capabilities=checked_client()
        if not capabilities.get('flows'):frappe.throw('WhatsApp Flows are not enabled for this account')
        return hub.execute(hub_arguments(choose('WhatsApp'),dict(arguments,operation='flows.'+operation)))
    except (HubError,ValueError):
        # A failed read changed nothing; only a failed change leaves its outcome unknown.
        if operation in READS:frappe.throw('WhatsApp forms could not be loaded right now. Try again in a minute.')
        frappe.throw('Flow operation could not be confirmed. Refresh its status before retrying a change.')


@frappe.whitelist(methods=['GET'])
def choices(message, after=None):
    from relay_core.messaging import readable_source
    source,channel,context=readable_source(message)
    if channel.channel!='WhatsApp' or context.get('group_id'):frappe.throw('Forms require a private WhatsApp conversation')
    hub,capabilities=checked_client()
    if not capabilities.get('flows'):return {'items':[],'next':None}
    result=hub.execute(hub_arguments(channel,{'operation':'flows.list','after':after or ''}))
    rows=[{key:row.get(key) for key in ('id','name','status')} for row in result.get('data',[]) if isinstance(row,dict) and row.get('status')=='PUBLISHED']
    paging=result.get('paging') or {}
    return {'items':rows,'next':(paging.get('cursors') or {}).get('after') if paging.get('has_more') else None}


@frappe.whitelist(methods=['GET'])
def screens(message, flow_id):
    from relay_core.messaging import readable_source
    source,channel,context=readable_source(message)
    if channel.channel!='WhatsApp' or context.get('group_id'):frappe.throw('Forms require a private WhatsApp conversation')
    hub,capabilities=checked_client()
    if not capabilities.get('flows'):frappe.throw('Forms are unavailable')
    result=hub.execute(hub_arguments(channel,{'operation':'flows.json','id':flow_id}))
    definition=result.get('flow_json') or {}
    return {'items':[{'id':row.get('id'),'title':row.get('title') or row.get('id')} for row in definition.get('screens',[])[:100] if isinstance(row,dict) and isinstance(row.get('id'),str)]}
