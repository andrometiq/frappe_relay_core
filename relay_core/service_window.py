"""Local WhatsApp reply-window evidence; provider admission remains authoritative.

Reference: https://business.whatsapp.com/policy (24 September 2026).
"""
import frappe
from relay_core.timeline import page_query


def status(contact, channel, endpoint=None):
    filters={'relay_contact':contact,'channel':channel,'direction':'Incoming','legacy_source':['is','not set']}
    if endpoint:filters['sender_endpoint']=endpoint
    rows=page_query(['name','sent_at','creation'],filters,1).run(as_dict=True)
    expires=None
    if rows:
        stamp=frappe.utils.get_datetime(rows[0].sent_at or rows[0].creation)
        # A future provider clock cannot extend the local reply window.
        stamp=min(stamp,frappe.utils.get_datetime(rows[0].creation))
        expires=frappe.utils.add_to_date(stamp,hours=24)
    remaining=max(0,(expires-frappe.utils.now_datetime()).total_seconds()) if expires else 0
    return {'open':remaining>0,'expires_at':expires,'remaining_seconds':remaining}


def require_open(contact, channel, endpoint=None):
    if not status(contact,channel,endpoint)['open']:
        frappe.throw('The WhatsApp reply window is closed. Choose an approved template to continue.')
