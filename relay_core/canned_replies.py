"""Bounded WhatsApp saved-reply library; editing remains permission checked in Desk."""
import frappe
from relay_core.permissions import require_access

@frappe.whitelist(methods=['GET'])
def directory(query='',after=None):
    require_access()
    if not isinstance(query,str) or len(query)>80:frappe.throw('Invalid search')
    if after is not None and (not isinstance(after,str) or len(after)>140):frappe.throw('Invalid cursor')
    configure='System Manager' in frappe.get_roles()
    filters={'channel':'WhatsApp'}
    # Communication users can use published replies without Desk configuration access.
    # Drafts remain visible only to the users who can configure this library.
    if not configure:filters['published']=1
    if after:filters['name']=['>',after]
    rows=frappe.get_all('Relay Canned Reply',filters=filters,or_filters=[['title','like','%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%']],fields=['name','title','body','reply_type','language','published'],order_by='name asc',page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None,'can_configure':configure}
