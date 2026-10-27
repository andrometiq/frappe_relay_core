"""Scheduled start of WhatsApp bulk campaigns. Times are in the site time zone."""
from datetime import datetime

import frappe

from relay_core.automation.service import internal_save

MAX_DAYS = 90
DUE_LIMIT = 20


def start_time(value) -> datetime:
    """The requested start, at least a minute ahead and at most MAX_DAYS ahead."""
    try:
        when = frappe.utils.get_datetime(value) if value else None
    except (TypeError, ValueError):
        when = None
    now = frappe.utils.now_datetime()
    if not when or when < frappe.utils.add_to_date(now, minutes=1):
        frappe.throw('Choose a start time in the future')
    if when > frappe.utils.add_to_date(now, days=MAX_DAYS):
        frappe.throw(f'Schedule a campaign at most {MAX_DAYS} days ahead')
    return when.replace(microsecond=0)


def start_due():
    """Start each due campaign. The scheduler calls this every minute."""
    names = frappe.get_all('Relay Campaign', filters={'status': 'Scheduled',
                           'scheduled_at': ['<=', frappe.utils.now_datetime()]},
                           pluck='name', order_by='scheduled_at asc', limit_page_length=DUE_LIMIT)
    for name in names:
        if claim(name):
            start(name)


def claim(name: str) -> bool:
    """Move a due campaign from Scheduled to Running under its row lock, so that only one worker starts it.
    A worker that loses the race reads Running, or gets a snapshot conflict when the winner committed first."""
    frappe.db.rollback()
    try:
        status = frappe.db.get_value('Relay Campaign', name, 'status', for_update=True)
    except frappe.QueryDeadlockError:
        status = None
    if status != 'Scheduled':
        frappe.db.rollback()
        return False
    frappe.db.set_value('Relay Campaign', name, {'status': 'Running', 'last_error': ''})
    frappe.db.commit()
    return True


def start(name: str):
    """Run the start checks as the user who scheduled the campaign; a failed check pauses it with the reason."""
    from relay_core import bulk_campaigns
    from relay_core.bulk_updates import changed, open_reply_window
    doc = frappe.get_doc('Relay Campaign', name)
    original = frappe.session.user
    try:
        if not frappe.db.get_value('User', doc.execution_user, 'enabled'):
            frappe.throw('The user who scheduled this campaign is disabled', frappe.PermissionError)
        frappe.set_user(doc.execution_user)
        doc.update(bulk_campaigns.check_ready(doc))
        doc.started_at = doc.started_at or frappe.utils.now_datetime()
        open_reply_window(doc.reply_window_hours)
        internal_save(doc)
        bulk_campaigns.enqueue('send_job', name, slot='control')  # Queued when this commits.
        changed(name)
        frappe.db.commit()
    except (frappe.ValidationError, frappe.PermissionError) as exc:
        frappe.db.rollback()
        frappe.db.set_value('Relay Campaign', name, {'status': 'Paused',
                            'last_error': f'The scheduled start failed: {exc}'[:500]})
        changed(name)
        frappe.db.commit()
    finally:
        frappe.set_user(original)
