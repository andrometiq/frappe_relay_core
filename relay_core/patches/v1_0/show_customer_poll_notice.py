import json

import frappe

from relay_core.message_types import POLL_REASONS


def execute():
    """Show the poll notice on customer polls and votes stored before it existed.

    Only message_data changes. Rows stored without Meta's unsupported type get it from their Hub event.
    """
    from_events = event_details()
    channels = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name')
    rows = frappe.get_all('Relay Message', fields=['name', 'provider_id', 'message_data'],
        filters={'message_type': 'unsupported', 'direction': 'Incoming', 'channel': ['in', channels or ['']]})
    for row in rows:
        data = json.loads(row.message_data or '{}')
        detail = from_events.get(row.provider_id) or data.get('unsupported') or {}
        if detail.get('type') not in POLL_REASONS or detail.get('code') == 131060:
            continue
        shown = {**data, 'kind': 'unsupported', 'unsupported': {**detail, 'reason': POLL_REASONS[detail['type']]}}
        if shown != data:
            frappe.db.set_value('Relay Message', row.name, 'message_data', json.dumps(shown, ensure_ascii=False),
                                update_modified=False)


def event_details() -> dict:
    """Meta's unsupported detail of each customer poll in the stored Hub events, by provider message ID."""
    from relay_core.automation.projection import extract_messages
    events = frappe.get_all('Relay Hub Event', pluck='payload',
        or_filters=[['payload', 'like', f'%{kind}%'] for kind in POLL_REASONS])
    details = {}
    for payload in events:
        try:
            rows = extract_messages(json.loads(payload))
        except (ValueError, TypeError, AttributeError):
            continue
        for row in rows:
            detail = (row.get('message_data') or {}).get('unsupported') or {}
            if detail.get('type') in POLL_REASONS:
                details[row['id']] = detail
    return details
