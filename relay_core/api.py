"""Permission-checked Core endpoints. Provider sends remain a Hub concern."""
import re
import frappe
from relay_core import ai_features
from relay_core.permissions import (require_access, readable_contact, contact_query, can_manage,
                                    can_configure, sees_all_teams)


def validate_reference(value, prefix):
    if prefix == 'CH':
        if not isinstance(value, str) or not value.strip() or len(value) > 140 or any(ord(c) < 32 for c in value):
            frappe.throw('Invalid Relay channel reference')
        return
    if not isinstance(value, str) or not re.fullmatch(r'RELAY-' + prefix + r'-[0-9]{10}', value):
        frappe.throw('Invalid Relay record reference')


@frappe.whitelist(methods=["GET", "POST"])
def channel_settings(name):
    require_access()
    validate_reference(name, 'CH')
    doc = frappe.get_doc('Relay Channel', name)
    doc.check_permission('read')
    # Never expose Password fields or a provider endpoint to communication users.
    return {key: doc.get(key) for key in ('name', 'channel', 'account', 'enabled')}


@frappe.whitelist(methods=["POST"])
def update_channel(name, account, enabled=0):
    require_access(configure=True)
    validate_reference(name, 'CH')
    doc = frappe.get_doc('Relay Channel', name)
    doc.check_permission('write')
    if not isinstance(account, str) or not account.strip() or len(account.strip()) > 140 or any(ord(c) < 32 for c in account):
        frappe.throw('Account must be a non-empty name of at most 140 characters')
    if type(enabled) not in (str, int, bool) or str(enabled) not in ('0', '1', 'True', 'False'):
        frappe.throw('Enabled must be 0 or 1')
    doc.account = account.strip()
    doc.enabled = int(enabled in (1, True, '1', 'True'))
    doc.save()
    return channel_settings(name)


@frappe.whitelist(methods=["GET", "POST"])
def messages(contact, before=None, after=None, channel=None, limit=50, sender_endpoint=None, query='', since=None):
    require_access()
    if sum(bool(value) for value in (before, after, since)) > 1:
        frappe.throw('Use one history cursor at a time')
    validate_reference(contact, 'CON')
    for value, prefix in ((channel, 'CH'), (before, 'MSG'), (after, 'MSG'), (since, 'MSG')):
        if value is not None:
            validate_reference(value, prefix)
    if isinstance(limit, bool) or not isinstance(limit, (str, int)) or not str(limit).isdigit() or int(limit) < 1:
        frappe.throw('Limit must be a positive integer')
    limit = min(int(limit), 100)
    readable_contact(contact)
    filters = {'relay_contact': contact}
    if not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query):
        frappe.throw('Message search must contain at most 200 printable characters')
    if sender_endpoint is not None:
        if not isinstance(sender_endpoint, str) or not 1 <= len(sender_endpoint) <= 200 or any(ord(c)<32 for c in sender_endpoint):
            frappe.throw('Invalid conversation endpoint')
        filters['sender_endpoint'] = sender_endpoint
    if channel:
        filters['channel'] = channel
    from relay_core.timeline import page_query
    watermark = page_query(['name'], filters, 1, contact=contact, ingestion=True, search=query).run(as_dict=True) if not since else []
    rows = page_query(
        ['name', 'channel', 'content', 'direction', 'status', 'creation', 'sent_at', 'provider_context',
         'message_type', 'message_data', 'reactions', 'edited_at', 'transcript', 'transcript_status', 'delivery_error', 'provider_id', 'sender_endpoint', 'send_group', 'legacy_author',
         'relay_contact', 'business_doctype', 'business_name'],
        filters, limit+1, before, since or after, contact, ingestion=bool(since), search=query).run(as_dict=True)
    more = len(rows) > limit
    rows = rows[:limit]
    channels = {}
    for channel_name in {row.channel for row in rows}:
        channels[channel_name] = frappe.get_doc('Relay Channel', channel_name)
        channels[channel_name].check_permission('read')
    from relay_core.message_display import decorate_messages
    decorate_messages(rows, channels)
    if not after and not since:
        rows.reverse()
    cursor = rows[-1].name if since and rows else since if since else watermark[0].name if watermark else 'RELAY-MSG-0000000000'
    return {'items': rows, 'has_more': more, 'ingestion_cursor': cursor,
        'first': rows[0].name if rows else None, 'last': rows[-1].name if rows else None}


@frappe.whitelist(methods=["GET"])
def contacts(query='', before=None, after=None, limit=50):
    """Permission-filtered, database searched keyset page; never counts all rows."""
    require_access()
    if not isinstance(query, str) or len(query) > 80 or any(ord(c) < 32 for c in query):
        frappe.throw('Search must contain at most 80 printable characters')
    if before and after:
        frappe.throw('Use one contact cursor at a time')
    for cursor in (before, after):
        if cursor is not None:
            validate_reference(cursor, 'CON')
    if isinstance(limit, bool) or not isinstance(limit, (str, int)) or not str(limit).isdigit() or int(limit) < 1:
        frappe.throw('Limit must be a positive integer')
    limit = min(int(limit), 50)
    filters = {}
    if before or after:
        filters['name'] = ['<' if before else '>', before or after]
    # Escape LIKE metacharacters, then allow gaps between literal characters.
    # This is subsequence matching, not typo correction. Values remain bound by Frappe.
    needle = query.strip()
    pattern = '%' + '%'.join('\\' + c if c in '%_\\' else c for c in needle) + '%'
    options = dict(filters=filters, fields=['name', 'contact', 'display_name'],
                   order_by='name desc' if before else 'name asc', limit=limit + 1)
    if needle:
        options['or_filters'] = [[field, 'like', pattern] for field in ('display_name', 'name')]
    from pypika.terms import LiteralValue
    search = frappe.qb.get_query('Relay Contact', ignore_permissions=False, **options)
    scope = contact_query()
    if scope:
        search = search.where(LiteralValue('(' + scope + ')'))
    rows = search.run(as_dict=True)
    more = len(rows) > limit
    rows = rows[:limit]
    if before:
        rows.reverse()
    items = [dict(row, id=row['name']) for row in rows]
    return {'items': items,
            'previous': {'before': items[0]['id']} if items and (more if before else bool(after)) else None,
            'next': {'after': items[-1]['id']} if items and (bool(before) if before else more) else None}


@frappe.whitelist(methods=['GET'])
def business_types():
    require_access()
    types = frappe.get_all('Relay Contact Type', filters={'enabled': 1},
        pluck='business_doctype', limit_page_length=200)
    return sorted({name for name in types if frappe.has_permission(name, 'read')})


@frappe.whitelist(methods=['GET'])
def business_records(doctype, query=''):
    require_access()
    if not isinstance(doctype, str) or not isinstance(query, str) or len(query)>80:
        frappe.throw('Invalid record search')
    if not frappe.db.exists('Relay Contact Type', {'business_doctype': doctype, 'enabled': 1}):
        frappe.throw('Business type is not configured', frappe.PermissionError)
    from relay_core.business_inbox import check_type
    from frappe.desk.search import search_link
    from frappe.utils import strip_html
    from html import unescape
    check_type(doctype)
    rows = search_link(doctype=doctype, txt=query, page_length=30, ignore_user_permissions=False)
    return [frappe._dict({'name': row['value'], 'value': row['value'],
             'label': unescape(strip_html(row.get('label') or row['value'])),
             'description': unescape(strip_html(row.get('description') or ''))}) for row in rows[:30]]


@frappe.whitelist(methods=['GET'])
def message_context(message, channel=None):
    require_access();validate_reference(message,'MSG')
    doc=frappe.get_doc('Relay Message',message);doc.check_permission('read');readable_contact(doc.relay_contact)
    frappe.get_doc('Relay Channel',doc.channel).check_permission('read')
    if channel and channel != doc.channel:
        frappe.throw('Message belongs to another channel')
    earlier=messages(doc.relay_contact,before=message,limit=25,channel=channel)
    later=messages(doc.relay_contact,after=message,limit=25,channel=channel)
    fields=['name','channel','content','direction','status','creation','sent_at','provider_context','message_type','message_data','reactions','edited_at','transcript','transcript_status','delivery_error','provider_id','sender_endpoint','send_group','legacy_author']
    row={key:doc.get(key) for key in fields}
    from relay_core.message_display import decorate_messages
    decorate_messages([row], {doc.channel: frappe.get_doc('Relay Channel', doc.channel)})
    return {'contact':doc.relay_contact,'items':earlier['items']+[row]+later['items'],'first':earlier['first'] or message,'has_more':earlier['has_more'],'has_newer':later['has_more'],'last':later['last'] or message,'anchor':message}


@frappe.whitelist(methods=['GET'])
def quoted_message(message):
    """Resolve only the source message's original channel/conversation quote."""
    from relay_core.automation.provenance import context_of
    from relay_core.message_updates import provider_key
    require_access(); validate_reference(message, 'MSG')
    source = frappe.get_doc('Relay Message', message)
    source.check_permission('read'); readable_contact(source.relay_contact)
    frappe.get_doc('Relay Channel', source.channel).check_permission('read')
    reference = context_of(source).get('reply_to_message_id')
    if not reference:
        return {'message': None}
    key = provider_key(source.channel, source.sender_endpoint, str(reference))
    name = frappe.db.get_value('Relay Message', {'provider_message_key': key, 'relay_contact': source.relay_contact}, 'name')
    if name:
        frappe.get_doc('Relay Message', name).check_permission('read')
    return {'message': name}


@frappe.whitelist(methods=['GET'])
def message_snapshots(contact, names):
    """Refresh visible edits, reactions and delivery states without moving history."""
    require_access(); readable_contact(contact)
    names=frappe.parse_json(names) if isinstance(names,str) else names
    if not isinstance(names,list) or len(names)>50:frappe.throw('Refresh at most 50 messages')
    for name in names:validate_reference(name,'MSG')
    rows=frappe.get_list('Relay Message',filters={'relay_contact':contact,'name':['in',names]},
        fields=['name','relay_contact','business_doctype','business_name','channel','content','direction','status','creation','sent_at','provider_context',
                'message_type','message_data','reactions','edited_at','transcript','transcript_status','delivery_error','provider_id','sender_endpoint','send_group','legacy_author'],page_length=50)
    channels = {row.channel: frappe.get_doc('Relay Channel', row.channel) for row in rows}
    for channel in channels.values():
        channel.check_permission('read')
    from relay_core.message_display import decorate_messages
    decorate_messages(rows, channels)
    return {'items':rows}


@frappe.whitelist(methods=['GET'])
def capabilities():
    require_access()
    from relay_core.channels import enabled
    channels=enabled()
    manage=can_manage()
    from relay_core.hub_channels import site_numbers
    enabled_names=[item.name for item in channels]
    return {'manage':manage, 'teams':manage, 'billing':frappe.has_permission('Relay WhatsApp Billing Month', 'read'),
            'multi_team':sees_all_teams(), 'configure':can_configure(),
            'ai':ai_features.is_enabled(),
            'skills':ai_features.is_enabled() and frappe.has_permission('Relay AI Skill', 'write'),
            'business_events':frappe.has_permission('Relay Business Event Rule', 'write'),
            'enabled_channels':enabled_names,
            'channels':{item.name:item.get_features() for item in channels},
            'whatsapp_numbers':site_numbers('WhatsApp') if 'WhatsApp' in enabled_names else []}


@frappe.whitelist(methods=['GET'])
def conversation_channels(contact):
    """Bounded verified channel metadata, independent of the loaded history page."""
    require_access()
    validate_reference(contact, 'CON')
    readable_contact(contact)
    endpoints = frappe.get_all('Relay Contact Endpoint',
        filters={'relay_contact': contact, 'verified': 1}, fields=['channel'],
        group_by='channel', limit_page_length=100)
    names = [row.channel for row in endpoints]
    if not names:
        return {'items': []}
    channels = frappe.get_list('Relay Channel', filters={'name': ['in', names], 'enabled': 1},
        fields=['name', 'channel'], order_by='channel asc', limit_page_length=100)
    from relay_core.inbox import unread_count
    return {'items': [{'value': row.name, 'label': row.channel, 'unread': unread_count(contact, row.name), 'translation_enabled': bool(frappe.conf.get('relay_automation_enabled') and ai_features.is_enabled() and frappe.db.exists('Relay Automation Policy', {'channel':row.name,'enabled':1,'allow_translation':1}))} for row in channels]}


@frappe.whitelist(methods=['GET'])
def contact_details(contact):
    """Read permitted business links and channel endpoint provenance for a Contact."""
    require_access()
    person = frappe.get_doc('Contact', contact)
    person.check_permission('read')
    configured = set(business_types())
    links = [{'doctype': row.link_doctype, 'name': row.link_name}
             for row in person.links
             if row.link_doctype in configured
             and frappe.get_doc(row.link_doctype, row.link_name).has_permission('read')]
    relay = frappe.db.get_value('Relay Contact', {'contact': contact}, 'name')
    endpoints, primary = [], None
    if relay:
        readable_contact(relay)
        from relay_core.business_access import primary_record
        primary = primary_record(relay)
        rows = frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': relay},
                             fields=['name', 'channel', 'endpoint', 'verified', 'creation', 'modified'],
                             limit_page_length=100)
        for row in rows:
            channel = frappe.get_doc('Relay Channel', row.channel)
            if channel.has_permission('read'):
                row.provider = channel.channel
                endpoints.append(row)
    can_edit_links = bool(person.has_permission('write'))
    return {'name': person.name, 'label': person.full_name or person.name,
            'phone': person.mobile_no or person.phone or '', 'relay_contact': relay,
            'links': links, 'primary': primary, 'endpoints': endpoints,
            'can_edit_links': can_edit_links, 'can_set_primary': can_edit_links and bool(relay)}


@frappe.whitelist(methods=['GET'])
def channel_options():
    """Safe local channel readiness; provider receipt health lives in Activity."""
    require_access()
    from relay_core.settings import value
    rows = frappe.get_list('Relay Channel', filters={'account': value('relay_hub_account')},
        fields=['name', 'channel', 'enabled', 'label', 'address', 'is_default'], order_by='channel asc', page_length=100)
    return {'items': rows}


@frappe.whitelist(methods=['GET'])
def contact_directory(query='', after=None):
    require_access()
    if not isinstance(query, str) or len(query) > 80 or (after is not None and (not isinstance(after, str) or len(after) > 140)):
        frappe.throw('Invalid contact search')
    filters = {'name': ['>', after]} if after else {}
    if query.strip():
        filters['full_name'] = ['like', '%' + query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%']
    rows = frappe.get_list('Contact', filters=filters, fields=['name', 'full_name', 'mobile_no'],
        order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['GET'])
def contact_profile(contact):
    require_access()
    doc, _ = readable_contact(contact)
    from relay_core.business_access import candidates, primary_record
    links = candidates(doc.name)
    readable = [link for link in links if frappe.has_permission(link[0], 'read', doc=link[1])]
    return {'name': doc.name, 'display_name': doc.display_name, 'contact': doc.contact,
            'primary': primary_record(doc.name, links), 'link_count': len(readable)}


@frappe.whitelist(methods=['GET'])
def contact_preferences(contact, business_doctype, business_name):
    require_access()
    from relay_core.conversation_start import business_contact
    business_contact(contact, business_doctype, business_name)
    return {'items': frappe.get_list('Relay Channel Preference', filters={
        'contact': contact, 'business_doctype': business_doctype, 'business_name': business_name},
        fields=['name', 'endpoint', 'consent', 'priority'], order_by='priority asc, name asc', page_length=100)}


@frappe.whitelist(methods=['POST'])
def save_contact_preference(contact, business_doctype, business_name, endpoint, consent, priority=10):
    require_access(configure=True)
    from relay_core.conversation_start import business_contact
    from relay_core.channel_preferences import scope_key
    business_contact(contact, business_doctype, business_name)
    binding = frappe.get_doc('Relay Contact Endpoint', endpoint)
    readable_contact(binding.relay_contact)
    frappe.get_doc('Relay Channel', binding.channel).check_permission('read')
    if frappe.db.get_value('Relay Contact', binding.relay_contact, 'contact') != contact:
        frappe.throw('Endpoint does not belong to this person', frappe.PermissionError)
    if consent not in ('Granted', 'Denied') or not str(priority).isdigit() or not 1 <= int(priority) <= 100:
        frappe.throw('Choose consent and a priority from 1 to 100')
    if consent == 'Granted' and not binding.verified:
        frappe.throw('Review the revoked identity before granting consent')
    scope = scope_key(contact, business_doctype, business_name)
    with frappe.cache.lock('relay-preference:' + scope, timeout=10):
        name = frappe.db.get_value('Relay Channel Preference', {'scope_key': scope, 'endpoint': endpoint}, 'name')
        doc = frappe.get_doc('Relay Channel Preference', name) if name else frappe.new_doc('Relay Channel Preference')
        doc.update(dict(contact=contact, business_doctype=business_doctype, business_name=business_name,
                        endpoint=endpoint, consent=consent, priority=int(priority)))
        doc.save()
    return {'name': doc.name, 'endpoint': doc.endpoint, 'consent': doc.consent, 'priority': doc.priority}


@frappe.whitelist(methods=['GET'])
def preview_document(doctype, name, action):
    """Filled template text, PDF file name and recipient contacts of a Relay Document Action."""
    from relay_core.document_actions import preview
    return preview(doctype, name, action)


@frappe.whitelist(methods=['POST'])
def send_document(doctype, name, action, contacts=None, request_key=None):
    """Send a Relay Document Action for one document: its template, variables and PDF.

    `contacts` (optional) is a list of Contact names of the business record; the default is the
    action's recipients. Repeating a `request_key` returns the earlier sends instead of sending again."""
    from relay_core.document_actions import send
    return send(doctype, name, action, contacts, request_key)
