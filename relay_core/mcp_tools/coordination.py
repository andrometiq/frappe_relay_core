"""Several actors on one chat: actor identity, chat claims, the reply guard, change cursors and the MCP audit log.

Claims live in Redis because they are short leases; a claim holder's pause of the Relay automation uses the
existing staff takeover (automation_paused) and is undone on release or, after expiry, by the next MCP call."""
import json
import re
import time

import frappe

from relay_core.mcp_tools.registry import READ, ToolError

CLAIMS = 'relay-mcp-claims'
CLIENT = 'relay-mcp-client:'
CLIENT_SECONDS = 30 * 86400
SENT = 'relay-mcp-sent:'
SENT_SECONDS = 86400
LOCK_SECONDS = 120
SUBJECT = 'MCP '
MAX_CLAIM_MINUTES = 30
CONTACT_ID = re.compile(r'^RELAY-CON-[0-9]{10}$')


def remember_client(info):
    """The clientInfo name of initialize, kept per API user; one user is one agent."""
    name = info.get('name') if isinstance(info, dict) else None
    if isinstance(name, str) and name.isprintable() and 0 < len(name) <= 80:
        frappe.cache.set_value(CLIENT + frappe.session.user, name, expires_in_sec=CLIENT_SECONDS)


def client_name():
    return frappe.cache.get_value(CLIENT + frappe.session.user) or ''


def run(entry, arguments):
    """A write or send under the chat's claim and reply guard, then one audit row."""
    arguments = dict(arguments)
    after = arguments.pop('after_message', None)
    contact = chat_of(arguments, after) if entry.chat else None
    if not contact:
        value = entry.handler(**arguments)
        audit(entry, arguments, value, None)
        return value
    sent_key = SENT + frappe.session.user + ':' + str(arguments.get('request_key') or arguments.get('message'))
    with chat_lock(contact):
        frappe.db.commit()  # A fresh snapshot sees the send another agent committed while we waited.
        if not frappe.cache.get_value(sent_key):  # A repeat of our own send only returns its first result.
            require_unclaimed(contact)
            if after:
                require_unchanged(contact, after)
        value = entry.handler(**arguments)
        audit(entry, arguments, value, contact)
        frappe.db.commit()  # Before the lock is released, so the next sender's guard sees this send.
        frappe.cache.set_value(sent_key, 1, expires_in_sec=SENT_SECONDS)
    if isinstance(value, dict):
        value = dict(value, sent_by=frappe.session.user, via='mcp', client=client_name())
    return value


def chat_lock(contact):
    """One sender at a time per chat, across web workers, for the guard check and the send."""
    return frappe.cache.lock(frappe.cache.make_key('relay-mcp-chat:' + contact), timeout=LOCK_SECONDS,
                             blocking_timeout=LOCK_SECONDS)


def chat_of(arguments, after=None):
    """The Relay Contact a send goes to, after the user's read check, or None when the tool names no chat."""
    from relay_core.permissions import readable_contact
    contact = None
    for message in (arguments.get('message'), after):
        if message and not contact:
            contact = frappe.db.get_value('Relay Message', message, 'relay_contact')
    given = arguments.get('contact')
    if not contact and isinstance(given, str):
        contact = given if CONTACT_ID.match(given) else frappe.db.get_value('Relay Contact', {'contact': given}, 'name')
    if not contact and arguments.get('number'):
        contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint': arguments['number'].lstrip('+'),
                                                                 'channel': arguments.get('channel')}, 'relay_contact')
    if contact:
        readable_contact(contact)
    return contact


def require_unclaimed(contact):
    claim = active_claim(contact)
    if claim and claim['user'] != frappe.session.user:
        raise ToolError(f'Chat claimed by {holder(claim)} until {stamp(claim["until"])}. Read changes_since and try later.')


def require_unchanged(contact, after):
    """Refuse a send when the chat has a message, or a send in flight, newer than the one the agent saw."""
    seen = frappe.db.get_value('Relay Message', after, ['relay_contact', 'creation'], as_dict=True)
    if not seen or seen.relay_contact != contact:
        raise ToolError('after_message must be a message of this chat')
    newer = frappe.get_list('Relay Message', filters={'relay_contact': contact, 'name': ['>', after]},
                            fields=['name', 'direction', 'content'], order_by='name asc', limit_page_length=5)
    if newer:
        summary = '; '.join(f'{row.direction} {row.name}: {(row.content or "")[:80]}' for row in newer)
        raise ToolError(f'Chat changed: {summary}. Read the chat again and pass the newest message as after_message.')
    from relay_core.messaging import actions
    pending = [row for row in actions(contact)['items'] if row['creation'] > seen.creation and row['status'] != 'Rejected']
    if pending:
        raise ToolError(f'Chat changed: a {pending[0]["operation"]} send ({pending[0]["status"]}) started after '
                        f'{after}. Read the chat again.')


def claims():
    """Active claims by contact; expired ones are released on the way."""
    rows = {contact: json.loads(value) for contact, value in (frappe.cache.hgetall(CLAIMS) or {}).items()}
    rows = {contact.decode() if isinstance(contact, bytes) else contact: value for contact, value in rows.items()}
    for contact, claim in list(rows.items()):
        if claim['until'] <= time.time():
            end_claim(contact, claim)
            del rows[contact]
    return rows


def active_claim(contact):
    return claims().get(contact)


def holder(claim):
    return claim['user'] + (f' ({claim["client"]})' if claim.get('client') else '')


def stamp(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def claim_chat(contact, minutes):
    from relay_core.permissions import readable_contact
    readable_contact(contact)
    with chat_lock(contact):
        current = active_claim(contact)
        if current and current['user'] != frappe.session.user:
            raise ToolError(f'Chat claimed by {holder(current)} until {stamp(current["until"])}')
        claim = current or {'user': frappe.session.user, 'client': client_name(), **pause_automation(contact)}
        claim['until'] = time.time() + minutes * 60
        frappe.cache.hset(CLAIMS, contact, json.dumps(claim))
    return public_claim(contact, claim)


def release_chat(contact):
    from relay_core.permissions import readable_contact
    readable_contact(contact)
    with chat_lock(contact):
        claim = active_claim(contact)
        if not claim:
            return {'contact': contact, 'released': False}
        if claim['user'] != frappe.session.user:
            raise ToolError(f'Only {holder(claim)} can release this claim before {stamp(claim["until"])}')
        end_claim(contact, claim)
    return {'contact': contact, 'released': True}


def pause_automation(contact):
    """Pause the Relay automation and AI for the claim through the staff takeover. Returns what to undo later."""
    if frappe.db.get_value('Relay Contact', contact, 'automation_paused'):
        return {'paused_generation': None, 'ai_paused': True}
    from relay_core.automation.service import takeover
    from relay_core.mcp_tools.registry import core_message
    try:
        return {'paused_generation': takeover(contact, 1)['generation'], 'ai_paused': True}
    except frappe.PermissionError as error:
        return {'paused_generation': None, 'ai_paused': False, 'ai_note': core_message(error) or 'automation pause not permitted'}


def end_claim(contact, claim):
    """Drop the claim and resume automation only when nobody changed the takeover since the claim paused it."""
    frappe.cache.hdel(CLAIMS, contact)
    if not claim.get('paused_generation'):
        return
    generation = frappe.db.get_value('Relay Contact', contact, 'automation_generation')
    if int(generation or 0) != int(claim['paused_generation']):
        return
    from relay_core.automation.service import takeover
    actor = frappe.session.user
    try:
        frappe.set_user(claim['user'])  # The resume undoes that user's own pause, under that user's rights.
        takeover(contact, 0)
    except frappe.PermissionError:
        frappe.log_error(title='Relay MCP claim could not resume automation')
    finally:
        frappe.set_user(actor)


def public_claim(contact, claim):
    return {'contact': contact, 'claimed_by': holder(claim), 'until': stamp(claim['until']), 'ai_paused': claim['ai_paused'],
            **({'ai_note': claim['ai_note']} if claim.get('ai_note') else {})}


def audit(entry, arguments, value, contact):
    """One Activity Log row per MCP write or send: actor, client, tool, chat and response time."""
    if entry.safety == READ:
        return
    given = arguments.get('contact')
    contact = contact or (given if isinstance(given, str) and CONTACT_ID.match(given) else None)
    result = value if isinstance(value, dict) else {}
    action = result.get('action') or (frappe.db.get_value('Relay Message Action', {'outbound_message': result['message']}, 'name')
                                      if result.get('message') else None)
    details = {'tool': entry.name, 'client': client_name(), 'request_key': arguments.get('request_key'),
               'message': result.get('message') or result.get('outbound_message'), 'response_seconds': response_seconds(contact)}
    frappe.get_doc({'doctype': 'Activity Log', 'subject': SUBJECT + entry.name, 'status': 'Success', 'user': frappe.session.user,
                    'reference_doctype': 'Relay Contact' if contact else None, 'reference_name': contact,
                    'link_doctype': 'Relay Message Action' if action else None, 'link_name': action,
                    'content': json.dumps(details, default=str)}).insert(ignore_permissions=True)


def response_seconds(contact):
    """Seconds since the customer's newest message in the chat, for reply-time analytics."""
    if not contact:
        return None
    rows = frappe.get_list('Relay Message', filters={'relay_contact': contact, 'direction': 'Incoming'}, fields=['creation'],
                           order_by='name desc', limit_page_length=1)
    return int((frappe.utils.now_datetime() - rows[0].creation).total_seconds()) if rows else None


def actors(messages):
    """Who sent each outgoing message: {name: {sent_by, via, client}}; via is mcp, automation, staff or system."""
    names = [row['name'] for row in messages if row.get('direction') == 'Outgoing']
    if not names:
        return {}
    sends = frappe.get_all('Relay Message Action', filters={'outbound_message': ['in', names]},
                           fields=['name', 'outbound_message', 'owner'])
    logged = {row.link_name: json.loads(row.content or '{}').get('client', '') for row in frappe.get_all(
        'Activity Log', filters={'link_doctype': 'Relay Message Action', 'link_name': ['in', [row.name for row in sends]]},
        fields=['link_name', 'content'])} if sends else {}
    found = {row.outbound_message: row for row in sends}
    return {name: describe(found.get(name), logged) for name in names}


def describe(send, logged):
    if not send:
        return {'sent_by': None, 'via': 'system'}
    if send.name in logged:
        return {'sent_by': send.owner, 'via': 'mcp', 'client': logged[send.name]}
    return {'sent_by': send.owner, 'via': 'automation' if send.owner in ('Administrator', 'Guest') else 'staff'}


def with_actors(rows):
    found = actors(rows)
    return [dict(row, **found.get(row.get('name'), {})) for row in rows]
