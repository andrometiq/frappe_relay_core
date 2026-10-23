"""Account-scoped template lifecycle records from authenticated Hub events."""
import hashlib
import frappe
from relay_core.automation.service import internal_save
from relay_core.settings import value as connection_value


def project(payload, event):
    applied = False
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            if change.get('field') != 'message_template_status_update': continue
            value = change.get('value') or {}
            identifier, status = value.get('message_template_id'), value.get('event')
            if type(identifier) not in (str, int) or not str(identifier).isdigit() or len(str(identifier)) > 100:
                raise ValueError('Invalid template identity')
            if status not in {'APPROVED','REJECTED','PENDING','PAUSED','DISABLED','IN_APPEAL','DELETED','PENDING_DELETION','REINSTATED','FLAGGED'}:
                raise ValueError('Invalid template status')
            key = hashlib.sha256((event.account + ':' + str(identifier)).encode()).hexdigest()
            # Serialize creation as well as later updates for this account.
            frappe.db.get_value('Relay Channel', {'account':event.account, 'channel':'WhatsApp'}, 'name', for_update=True)
            name = frappe.db.get_value('Relay WhatsApp Template', {'record_key':key}, 'name')
            doc = frappe.get_doc('Relay WhatsApp Template', name) if name else frappe.get_doc({'doctype':'Relay WhatsApp Template','record_key':key})
            applied = True
            if name and int(doc.hub_event_id) >= int(event.hub_event_id): continue
            doc.update({'account':event.account,'template_id':str(identifier),'template_name':value.get('message_template_name'),
                        'language':value.get('message_template_language'),'status':status,'reason':value.get('reason'),
                        'hub_event_id':event.hub_event_id})
            internal_save(doc, new=not name)
            frappe.publish_realtime('relay_changed', {'kind':'templates'},
                room=frappe.realtime.get_doctype_room('Relay WhatsApp Template'), after_commit=True)
    return applied


def overlay(page):
    """Hub supplies template content; pushed lifecycle evidence supplies status."""
    rows = page.get('data') or []
    if not rows: return page
    states = {row.template_id:row for row in frappe.get_all('Relay WhatsApp Template',
        filters={'account':connection_value('relay_hub_account'),'template_id':['in',[str(row['id']) for row in rows]]},
        fields=['template_id','status','reason'])}
    return dict(page, data=[dict(row, status=states[str(row['id'])].status,
        rejected_reason=states[str(row['id'])].reason) if str(row['id']) in states else row for row in rows])
