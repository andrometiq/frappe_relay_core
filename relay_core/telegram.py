"""Permission-checked Core facade for account-scoped Telegram group services."""
import hashlib
import frappe
from relay_core.settings import value as connection_value
from relay_core.permissions import require_access
from relay_core.automation.provenance import integer
from relay_core.whatsapp import client


OPERATIONS = {'info', 'member', 'count', 'administrators', 'title', 'description', 'permissions',
    'invite.create', 'invite.edit', 'invite.revoke', 'requests.approve', 'requests.reject',
    'members.ban', 'members.unban', 'members.restrict', 'members.promote', 'leave',
    'topics.create', 'topics.edit', 'topics.close', 'topics.reopen', 'topics.delete',
    'pins.pin', 'pins.unpin', 'pins.unpin_all', 'photo.set', 'photo.delete',
    'topics.general.edit', 'topics.general.close', 'topics.general.reopen', 'topics.general.hide',
    'topics.general.unhide', 'topics.general.unpin_all', 'topics.unpin_all',
    'members.ban_sender', 'members.unban_sender', 'members.title'}
ARGUMENTS = {'chat_id', 'user_id', 'message_thread_id', 'message_id', 'title', 'description',
    'name', 'invite_link', 'expire_date', 'until_date', 'member_limit', 'creates_join_request',
    'only_if_banned', 'revoke_messages', 'disable_notification', 'permissions', 'administrator_rights',
    'photo_base64', 'sender_chat_id', 'custom_title'}


@frappe.whitelist(methods=['POST'])
def groups(operation, arguments=None):
    # Group administration is account-wide and is restricted to managers.
    require_access(manage=True)
    if not isinstance(operation, str) or operation not in OPERATIONS:
        frappe.throw('Unsupported Telegram group operation')
    if isinstance(arguments, str):
        arguments = frappe.parse_json(arguments)
    if not isinstance(arguments, dict) or set(arguments) - ARGUMENTS:
        frappe.throw('Invalid Telegram group arguments')
    integer(arguments.get('chat_id'))
    if arguments['chat_id'] >= 0:
        frappe.throw('Select a Telegram group or supergroup')
    result = client().telegram_groups(operation, **arguments)
    from relay_core.telegram_topics import action
    try:action(operation, arguments, result)
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title='Relay Telegram topic cache', message='Provider action succeeded but local topic metadata could not be recorded. A later forum event can refresh it.')
    return result


@frappe.whitelist(methods=['POST'])
def execute(operation, arguments=None):
    """Core API alias; both facades use the canonical Hub telegram.groups tool."""
    return groups(operation, arguments)


@frappe.whitelist(methods=['POST'])
def send(chat_id, text, reply_to=0, message_thread_id=0, request_key=None, business_doctype=None, business_name=None):
    require_access()
    integer(chat_id)
    if not isinstance(text, str) or not 1 <= len(text) <= 4096:
        frappe.throw('Telegram message must contain 1–4096 characters')
    for value in (reply_to, message_thread_id):
        if value != 0:
            integer(value, positive=True)
        elif type(value) is not int:
            frappe.throw('Invalid Telegram message reference')
    account = connection_value('relay_hub_account')
    if not account:
        frappe.throw('Configure the Relay Hub account first')
    channels = frappe.get_all('Relay Channel', filters={'account': account, 'channel': 'Telegram', 'enabled': 1}, pluck='name', limit_page_length=2)
    if len(channels) != 1:
        frappe.throw('Configure one enabled Telegram channel for this account')
    key = hashlib.sha256((channels[0] + ':' + str(chat_id)).encode()).hexdigest()
    contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key, 'verified': 1}, 'relay_contact')
    if not contact:
        frappe.throw('Telegram chat must have a verified contact binding',frappe.PermissionError)
    from relay_core.permissions import readable_contact
    readable_contact(contact)
    frappe.get_doc('Relay Channel', channels[0]).check_permission('read')
    from relay_core.telegram_delivery import send_group
    return send_group(contact, channels[0], chat_id, text, reply_to, message_thread_id, request_key, business_doctype, business_name)



@frappe.whitelist(methods=['GET'])
def group_chats(after=None, limit=30, query=""):
    """Bounded directory of verified groups for this site's account."""
    require_access(manage=True)
    from relay_core.api import validate_reference
    if after:
        validate_reference(after, 'CE')
    if isinstance(limit, bool) or not str(limit).isdigit() or not 1 <= int(limit) <= 50:
        frappe.throw('Limit must be between 1 and 50')
    if not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query):
        frappe.throw('Invalid group search')
    account = connection_value('relay_hub_account')
    channels = frappe.get_list('Relay Channel', filters={'account': account,
        'channel': 'Telegram', 'enabled': 1}, pluck='name', page_length=2) if account else []
    if len(channels) != 1:
        return {'items': [], 'next': None, 'configured': False}
    endpoint=frappe.qb.DocType('Relay Contact Endpoint')
    contact=frappe.qb.DocType('Relay Contact')
    directory=(frappe.qb.from_(endpoint).select(endpoint.name,endpoint.endpoint,endpoint.relay_contact)
        .where((endpoint.channel==channels[0]) & (endpoint.verified==1) & endpoint.endpoint.like('-%')))
    if after:directory=directory.where(endpoint.name>after)
    if query.strip():
        from pypika.functions import Lower
        text=query.strip().lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        pattern='%'+text+'%'
        contacts=frappe.qb.from_(contact).select(contact.name).where(Lower(contact.display_name).like(pattern))
        directory=directory.where(endpoint.endpoint.like(pattern)|endpoint.relay_contact.isin(contacts))
    # Contact permissions are checked before exposing a matching label.
    rows=directory.orderby(endpoint.name).limit(int(limit)+1).run(as_dict=True)
    from relay_core.permissions import readable_contact
    items = []
    for row in rows[:int(limit)]:
        try:
            relay, _ = readable_contact(row.relay_contact)
        except frappe.PermissionError:
            continue
        try:
            chat_id = int(row.endpoint)
            integer(chat_id)
        except (ValueError, TypeError):
            continue
        if chat_id >= 0:
            continue
        items.append({'name': row.name, 'chat_id': chat_id,
            'label': relay.display_name or row.endpoint, 'contact': row.relay_contact, 'channel': channels[0]})
    return {'items': items, 'next': rows[int(limit)-1].name if len(rows)>int(limit) else None,
        'configured': True}
