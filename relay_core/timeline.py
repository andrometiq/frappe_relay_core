"""Chronological history with stable tie-breaking and permission-checked cursors."""
from datetime import datetime, timezone
import frappe
from pypika import Order
from pypika.functions import Coalesce


def provider_time(payload, row=None):
    value = (row or {}).get('timestamp') or payload.get('occurred_at')
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            stamp = datetime.fromtimestamp(float(value), timezone.utc)
        else:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        return frappe.utils.convert_utc_to_system_timezone(stamp.astimezone(timezone.utc).replace(tzinfo=None)).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def timeline_time():
    """Effective message time that orders every thread."""
    message = frappe.qb.DocType('Relay Message')
    return (message.relay_timeline_time if frappe.conf.db_type != 'postgres' and frappe.db.has_column('Relay Message','relay_timeline_time')
            else Coalesce(message.sent_at, message.creation))


def page_query(fields, filters, limit, before=None, after=None, contact=None, ingestion=False, search=''):
    message = frappe.qb.DocType('Relay Message')
    timestamp = timeline_time()
    query = frappe.qb.get_query('Relay Message', fields=fields, filters=filters,
                               ignore_permissions=False, order_by='', limit=limit)
    if search.strip():
        # Voice notes are found by their transcript as well as their preview.
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.where(message.content.like(pattern) | message.transcript.like(pattern))
    # Preserve the public start-of-history cursor used by API clients.
    if before or after and after != 'RELAY-MSG-0000000000':
        anchor = frappe.get_doc('Relay Message', before or after)
        anchor.check_permission('read')
        from relay_core.permissions import readable_contact
        readable_contact(anchor.relay_contact)
        frappe.get_doc('Relay Channel', anchor.channel).check_permission('read')
        if contact and anchor.relay_contact != contact:
            frappe.throw('History cursor belongs to another conversation', frappe.PermissionError)
        value = anchor.sent_at or anchor.creation
        condition = ((timestamp > value) | ((timestamp == value) & (message.name > anchor.name))) if after else ((timestamp < value) | ((timestamp == value) & (message.name < anchor.name)))
        if ingestion: condition = message.name > anchor.name if after else message.name < anchor.name
        query = query.where(condition)
    order = Order.asc if after else Order.desc
    if ingestion: return query.orderby(message.name, order=order)
    return query.orderby(timestamp, order=order).orderby(message.name, order=order)


def install_indexes():
    """Index the effective timestamp on both supported database engines."""
    if frappe.conf.db_type != 'postgres':
        frappe.db.commit()  # MariaDB schema changes implicitly commit.
        if not frappe.db.has_column('Relay Message','relay_timeline_time'):
            frappe.db.sql('ALTER TABLE `tabRelay Message` ADD COLUMN `relay_timeline_time` DATETIME(6) GENERATED ALWAYS AS (COALESCE(`sent_at`,`creation`)) VIRTUAL')
        for name,scope in (
            ('relay_contact_time',['relay_contact']),
            ('relay_channel_time',['relay_contact','channel']),
            ('relay_endpoint_time',['relay_contact','channel','sender_endpoint']),
        ):
            frappe.db.add_index('Relay Message',scope+['relay_timeline_time','name'],name)
        frappe.clear_cache(doctype='Relay Message')
        return
    for name, scope in (
        ('relay_contact_time', 'relay_contact'),
        ('relay_channel_time', 'relay_contact, channel'),
        ('relay_endpoint_time', 'relay_contact, channel, sender_endpoint'),
    ):
        frappe.db.sql(f'CREATE INDEX IF NOT EXISTS "{name}" ON "tabRelay Message" ({scope}, (COALESCE(sent_at, creation)), name)')
