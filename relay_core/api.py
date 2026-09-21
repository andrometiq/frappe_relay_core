"""Permission-checked Core endpoints. Provider sends remain a Hub concern."""
import re
import frappe
from relay_core.permissions import require_access


@frappe.whitelist()
def channel_settings(name):
    require_access()
    doc = frappe.get_doc('Relay Channel', name)
    doc.check_permission('read')
    # Never expose Password fields or a provider endpoint to communication users.
    return {key: doc.get(key) for key in ('name', 'channel', 'account', 'enabled')}


@frappe.whitelist()
def update_channel(name, account, enabled=0):
    require_access(configure=True)
    doc = frappe.get_doc('Relay Channel', name)
    doc.check_permission('write')
    doc.account = account
    doc.enabled = frappe.utils.cint(enabled)
    doc.save()
    return channel_settings(name)


@frappe.whitelist()
def messages(contact, before=None, after=None, channel=None, limit=50):
    require_access()
    if before and after:
        frappe.throw('Use one history cursor at a time')
    for value, prefix in ((contact, 'CON'), (channel, 'CH'), (before, 'MSG'), (after, 'MSG')):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'RELAY-' + prefix + r'-[0-9]{10}', value)):
            frappe.throw('Invalid Relay record reference')
    limit = max(1, min(frappe.utils.cint(limit), 100))
    frappe.get_doc('Relay Contact', contact).check_permission('read')
    filters = {'relay_contact': contact}
    if channel:
        filters['channel'] = channel
    if before:
        filters['name'] = ['<', before]
    elif after:
        filters['name'] = ['>', after]
    # get_list applies Frappe permission rules; do not replace with get_all.
    rows = frappe.get_list('Relay Message', filters=filters,
        fields=['name', 'channel', 'content', 'direction', 'status', 'creation'],
        order_by='name asc' if after else 'name desc', page_length=limit+1)
    more = len(rows) > limit
    rows = rows[:limit]
    if not after:
        rows.reverse()
    return {'items': rows, 'has_more': more,
        'first': rows[0].name if rows else None, 'last': rows[-1].name if rows else None}
