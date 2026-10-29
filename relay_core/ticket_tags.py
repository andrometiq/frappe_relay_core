"""Ticket comments and notifications. Assignees and mentioned users get Frappe notifications."""
import html
import frappe
from relay_core.permissions import require_access
from relay_core.api import validate_reference

MAX_MENTIONS = 10


def user_list(values, limit=MAX_MENTIONS):
    values = frappe.parse_json(values) if isinstance(values, str) else values or []
    if (not isinstance(values, list) or len(values) > limit
            or any(not isinstance(user, str) or not user or len(user) > 140 for user in values)
            or len(set(values)) != len(values)):
        frappe.throw(f'Choose at most {limit} distinct colleagues')
    return values


def can_follow(ticket, user):
    """An enabled Relay user who can read every message linked to the ticket."""
    from relay_core.tickets import permission
    if not user or user == 'Guest' or not frappe.db.get_value('User', user, 'enabled'):
        return False
    return frappe.has_permission('Relay Contact', 'read', user=user) and bool(permission(ticket, user))


def message_business(names):
    """The one business all messages are explicitly filed under, when the caller can read it."""
    targets = {tuple(frappe.db.get_value('Relay Message', name, ['business_doctype', 'business_name']) or ())
               for name in names}
    if len(targets) != 1:
        frappe.throw('Select messages from the same business record')
    target = targets.pop()
    if len(target) != 2 or not all(target):
        return None, None
    if not frappe.has_permission(target[0], 'read', doc=target[1]):
        frappe.throw('You cannot read the business record', frappe.PermissionError)
    return target


def on_update(doc):
    """Notify a new assignee. Internal episode transitions stay silent."""
    from relay_core.tickets import _episode_transition
    if _episode_transition.get() is doc:
        return
    previous = doc.get_doc_before_save()
    assignee = doc.get('assigned_to')
    actor = frappe.utils.get_fullname(frappe.session.user)
    if assignee and assignee != (previous.get('assigned_to') if previous else None):
        notify(doc, [assignee], 'Assignment', f'{actor} assigned you a ticket')


def notify(doc, users, kind, action):
    """Write a Notification Log and send a live notice to each user who can still read the ticket."""
    from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
    actor = frappe.session.user
    users = [user for user in dict.fromkeys(users) if user != actor and can_follow(doc, user)]
    if not users:
        return []
    make_notification_logs({'type': kind, 'document_type': 'Relay Ticket', 'document_name': doc.name,
        'from_user': actor, 'link': '/relay#/tickets?ticket=' + doc.name,
        'subject': f'{html.escape(action)}: <b>{html.escape(doc.subject)}</b>'}, users)
    for user in users:
        frappe.publish_realtime('relay_ticket_notice', {'ticket': doc.name, 'subject': doc.subject,
            'action': action, 'kind': kind}, user=user, after_commit=True)
    return users


def locked_ticket(name):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name, for_update=True)
    doc.check_permission('write')
    return doc


@frappe.whitelist(methods=['GET'])
def comments(name):
    from relay_core.tickets import read
    read(name)
    rows = frappe.get_all('Comment', filters={'reference_doctype': 'Relay Ticket', 'reference_name': name,
        'comment_type': 'Comment'}, fields=['name', 'content', 'owner', 'creation'],
        order_by='creation desc', limit_page_length=100)
    return [{'name': row.name, 'body': html.unescape(row.content or ''), 'author': row.owner,
             'author_name': frappe.utils.get_fullname(row.owner), 'creation': row.creation}
            for row in reversed(rows)]


@frappe.whitelist(methods=['POST'])
def add_comment(name, body, mentions=None):
    """Mentioned users must read the ticket; they get a notification."""
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 4000:
        frappe.throw('Comment must contain 1–4000 characters')
    users = user_list(mentions)
    doc = locked_ticket(name)
    if any(not can_follow(doc, user) for user in users):
        frappe.throw('A mentioned colleague cannot access this conversation', frappe.PermissionError)
    frappe.get_doc({'doctype': 'Comment', 'comment_type': 'Comment', 'reference_doctype': 'Relay Ticket',
        'reference_name': doc.name, 'content': html.escape(body.strip()), 'comment_email': frappe.session.user,
        'comment_by': frappe.utils.get_fullname(frappe.session.user)}).insert(ignore_permissions=True)
    from relay_core.realtime import changed
    changed(doc)
    notify(doc, users, 'Mention', f'{frappe.utils.get_fullname(frappe.session.user)} mentioned you on a ticket')
    return comments(name)
