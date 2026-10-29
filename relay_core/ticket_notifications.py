"""Opt-in ticket notifications, restricted to a subscriber's verified endpoint."""
import hashlib
from contextvars import ContextVar
import frappe
from relay_core.business_access import document_name, business_document
from relay_core.permissions import require_access, readable_contact
from relay_core import tickets


outgoing_notification = ContextVar('relay_ticket_notification', default=None)
message_ownership = ContextVar('relay_notification_message_ownership', default=None)

def digest(*parts):
    return hashlib.sha256(':'.join(parts).encode()).hexdigest()


def destination(name):
    document_name(name)
    endpoint = frappe.get_doc('Relay Contact Endpoint', name)
    # Endpoint configuration is administrator-only. This facade exposes only
    # verified endpoints belonging to the current user's readable Contact.
    if not endpoint.verified:
        frappe.throw('Choose a verified notification endpoint', frappe.PermissionError)
    _, person = readable_contact(endpoint.relay_contact)
    email = (frappe.db.get_value('User', frappe.session.user, 'email') or '').lower()
    if person.get('user') != frappe.session.user and email not in {
        (row.email_id or '').lower() for row in person.email_ids
    }:
        frappe.throw('Notifications can only use your own contact endpoint', frappe.PermissionError)
    channel = frappe.get_doc('Relay Channel', endpoint.channel)
    channel.check_permission('read')
    if not channel.enabled or channel.channel not in ('Email', 'Telegram'):
        frappe.throw('Ticket notifications support enabled email or Telegram channels')
    return endpoint, channel


def validate_subscription(doc):
    require_access()
    if doc.user != frappe.session.user or doc.owner != frappe.session.user:
        frappe.throw('Manage only your own subscriptions', frappe.PermissionError)
    tickets.read(doc.ticket)
    if doc.subscription_key != digest(doc.ticket, doc.user):
        frappe.throw('Invalid subscription key')
    previous = doc.get_doc_before_save()
    if previous and (previous.ticket != doc.ticket or previous.user != doc.user):
        frappe.throw('A subscription cannot be moved to another ticket or user')
    destination(doc.destination)


@frappe.whitelist(methods=['GET'])
def subscription(ticket):
    tickets.read(ticket)
    return frappe.db.get_value('Relay Ticket Subscription', {'subscription_key': digest(ticket, frappe.session.user)},
        ['name', 'destination', 'enabled'], as_dict=True) or {}


@frappe.whitelist(methods=['POST'])
def subscribe(ticket, endpoint='', enabled=1):
    tickets.read(ticket)
    if str(enabled) not in ('0', '1', 'True', 'False'):
        frappe.throw('Invalid subscription flag')
    key = digest(ticket, frappe.session.user)
    with frappe.cache.lock('relay-ticket-subscription-'+ticket, timeout=10, blocking_timeout=3):
        name = frappe.db.get_value('Relay Ticket Subscription', {'subscription_key': key}, 'name')
        if not name and len(frappe.get_all('Relay Ticket Subscription', filters={'ticket':ticket}, pluck='name', limit_page_length=100)) >= 100:
            frappe.throw('This ticket has reached its subscriber limit')
        doc = frappe.get_doc('Relay Ticket Subscription', name) if name else frappe.new_doc('Relay Ticket Subscription')
        doc.update({'ticket': ticket, 'user': frappe.session.user, 'subscription_key': key,
                    'destination': endpoint or doc.get('destination'), 'enabled': int(str(enabled) in ('1', 'True'))})
        # Revocation must remain possible after an endpoint loses access.
        if not doc.enabled and name:
            doc.check_permission('write')
            doc.db_set('enabled', 0)
        else:
            doc.save()
        frappe.db.commit()
    return subscription(ticket)


@frappe.whitelist(methods=['GET'])
def destinations(query='', after=None):
    require_access()
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid endpoint search')
    from frappe.query_builder.functions import Lower
    endpoint = frappe.qb.DocType('Relay Contact Endpoint')
    relay = frappe.qb.DocType('Relay Contact')
    person = frappe.qb.DocType('Contact')
    address = frappe.qb.DocType('Contact Email')
    user_email = (frappe.db.get_value('User', frappe.session.user, 'email') or '').lower()
    search = (frappe.qb.from_(endpoint).join(relay).on(endpoint.relay_contact == relay.name)
              .join(person).on(relay.contact == person.name)
              .left_join(address).on((address.parent == person.name) & (address.parenttype == 'Contact'))
              .select(endpoint.name).distinct().where(endpoint.verified == 1)
              .where((person.user == frappe.session.user) | (Lower(address.email_id) == user_email)))
    if after:
        from relay_core.api import validate_reference
        validate_reference(after, 'CE')
        search = search.where(endpoint.name > after)
    if query:
        search = search.where(endpoint.endpoint.like('%'+query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')+'%'))
    rows = search.orderby(endpoint.name).limit(31).run(as_dict=True)
    items = []
    for row in rows[:30]:
        try:
            endpoint, channel = destination(row.name)
        except (frappe.PermissionError, frappe.ValidationError):
            continue
        items.append({'value': endpoint.name, 'label': channel.channel+' · '+endpoint.endpoint})
    return {'items': items, 'next': rows[29].name if len(rows)>30 else None}


def on_update(doc, method=None):
    previous = doc.get_doc_before_save()
    if not previous or (previous.get('ticket_status') == doc.get('ticket_status') and previous.get('assigned_to') == doc.get('assigned_to')):
        return
    # Ticket changes are transactionally journaled. Recovery submits with the same
    # provider request key after crashes, including a crash after provider acceptance.
    subscriptions = frappe.get_all('Relay Ticket Subscription', filters={'ticket':doc.name, 'enabled':1},
                                   fields=['name'], limit_page_length=101)
    if len(subscriptions)>100:
        frappe.throw('Ticket notification subscriber limit exceeded')
    body = f'{doc.name}: {doc.subject}\nStatus: {doc.get("ticket_status")}\nAssigned to: {doc.get("assigned_to") or "Unassigned"}'
    body += '\n'+frappe.utils.get_url('/relay#/tickets?ticket='+doc.name)
    old = getattr(frappe.flags, 'relay_automation_internal', False)
    frappe.flags.relay_automation_internal = True
    try:
        for row in subscriptions:
            key = digest(doc.name, str(doc.modified), row.name)
            if not frappe.db.exists('Relay Ticket Notification', {'event_key':key}):
                frappe.get_doc({'doctype':'Relay Ticket Notification', 'ticket':doc.name,
                    'subscription':row.name, 'event_key':key, 'body':body, 'status':'Pending'}).insert(ignore_permissions=True)
    finally:
        frappe.flags.relay_automation_internal = old
    frappe.enqueue('relay_core.ticket_notifications.recover', enqueue_after_commit=True)


def authorized(row):
    sub = frappe.get_doc('Relay Ticket Subscription', row.subscription)
    if not sub.enabled or not frappe.db.get_value('User', sub.user, 'enabled'):
        raise frappe.PermissionError('Subscription disabled')
    if frappe.session.user != sub.user:
        raise frappe.PermissionError('Subscription owner changed')
    endpoint, channel = destination(sub.destination)
    return endpoint, channel, business_context(row)


def business_context(row):
    """Resolve one readable ticket business, including pre-snapshot tickets."""
    from relay_core.business_access import reference
    ticket = tickets.read(row.ticket)
    businesses = {reference(frappe.get_doc('Relay Message', item['message'])) for item in ticket['messages']}
    explicit = (ticket.get('business_doctype'), ticket.get('business_name'))
    if any(explicit):
        businesses.add(explicit)
    if len(businesses) != 1 or None in businesses:
        raise frappe.PermissionError('Ticket must have one business for notifications')
    business = next(iter(businesses))
    if not all(business):raise frappe.PermissionError('Ticket business is incomplete')
    business_document(*business)
    return business


def recipient_business(contact, channel, address, doctype=None, name=None, notification=None, *, snapshot=False):
    """A subscription authorizes its own recipient independently of ticket ownership."""
    notification = notification or outgoing_notification.get()
    if not notification:
        from relay_core.business_access import choose_business
        return choose_business(contact, doctype, name)
    row = frappe.get_doc('Relay Ticket Notification', notification)
    if snapshot and doctype and name:
        # Recording a provider receipt must survive unsubscribe or a late success after rejection.
        sub = frappe.get_doc('Relay Ticket Subscription', row.subscription)
        if sub.user != frappe.session.user:
            raise frappe.PermissionError('Notification owner changed')
        business_document(doctype, name)
        return doctype, name
    if row.status != 'Pending':raise frappe.PermissionError('Notification is no longer pending')
    endpoint, target, business = authorized(row)
    if (endpoint.relay_contact, target.name, endpoint.endpoint) != (contact, channel, address):
        raise frappe.PermissionError('Notification destination changed')
    if (doctype or name) and (doctype, name) != business:
        raise frappe.PermissionError('Notification business changed')
    return business


def insert_message(doc, action):
    """Only a validated durable notification may cross contact business links."""
    from relay_core.messaging import object_value
    payload = object_value(action.payload)
    if payload.get('notification'):
        business = recipient_business(doc.relay_contact, doc.channel, doc.sender_endpoint,
            doc.business_doctype, doc.business_name, payload['notification'], snapshot=True)
        if list(business) != payload.get('business'):
            raise frappe.PermissionError('Notification snapshot changed')
        doc.ticket_notification = payload['notification']
        token = message_ownership.set((doc.relay_contact, doc.channel, doc.sender_endpoint, *business, doc.ticket_notification))
        try:
            return doc.insert(ignore_permissions=True)
        finally:
            message_ownership.reset(token)
    return doc.insert(ignore_permissions=True)


def authorize_action(action):
    from relay_core.messaging import object_value
    payload = object_value(action.payload)
    name = payload.get('notification')
    if not name: return
    row = frappe.get_doc('Relay Ticket Notification', name)
    if row.status != 'Pending': raise frappe.PermissionError('Notification is no longer pending')
    endpoint, channel, business = authorized(row)
    if payload.get('business') and tuple(payload['business']) != business:
        raise frappe.PermissionError('Notification business changed')
    recipient = payload['email_values']['to'][0] if action.operation == 'email' else str(payload['group']['chat_id'])
    if channel.name != action.target_channel or endpoint.endpoint != recipient:
        raise frappe.PermissionError('Notification destination changed')


def complete(action):
    from relay_core.messaging import object_value
    name = object_value(action.payload).get('notification')
    if not name or action.status not in ('Submitted', 'Rejected'): return
    set_outcome(name,action.status)


def set_outcome(name,status,reason=None):
    # A late success is evidence of delivery even after local revocation.
    current=frappe.db.get_value('Relay Ticket Notification',name,'status',for_update=True)
    if current=='Submitted':return
    frappe.db.set_value('Relay Ticket Notification',name,{'status':status,
        'reason':'' if status=='Submitted' else reason or 'Delivery rejected','next_attempt':None})


def defer(row):
    if frappe.db.get_value('Relay Ticket Notification',row.name,'status',for_update=True)!='Pending':return
    row.reload()
    attempts = int(row.attempts or 0)+1
    frappe.db.set_value('Relay Ticket Notification', row.name, {'attempts':attempts,
        'next_attempt':frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=min(60, 2**min(attempts,6))),
        'reason':'Delivery not confirmed; recovery uses the same request key'})


def dispatch(name):
    from relay_core import messaging
    with frappe.cache.lock('relay-ticket-notification-'+name, timeout=90, blocking_timeout=1):
        row = frappe.get_doc('Relay Ticket Notification', name)
        if row.status != 'Pending': return
        sub = frappe.get_doc('Relay Ticket Subscription', row.subscription)
        actor = frappe.session.user
        token = outgoing_notification.set(name)
        try:
            frappe.set_user(sub.user)
            endpoint, channel, (business_doctype, business_name) = authorized(row)
            key = 'ticket-'+row.event_key
            keys = [digest(sub.user, key), digest('email', sub.user, key), key]
            existing = frappe.db.get_value('Relay Message Action', {'request_key':['in',keys], 'owner':sub.user}, 'name')
            if existing:
                action = frappe.get_doc('Relay Message Action', existing)
                if messaging.object_value(action.payload).get('notification') != name:
                    raise ValueError('Request key belongs to another notification')
                result = messaging.reconcile(existing)
            elif channel.channel == 'Email':
                from relay_core.email import send
                result = send([endpoint.endpoint], 'Ticket update: '+row.ticket, row.body, request_key=key, auto_submitted=1,
                    channel_name=channel.name, business_doctype=business_doctype, business_name=business_name)
            else:
                from relay_core.telegram import send
                result = send(int(endpoint.endpoint), row.body, request_key=key,
                    business_doctype=business_doctype, business_name=business_name)
            status = result.get('status')
            if status in ('Submitted','Rejected'):
                set_outcome(name,status)
            else:
                defer(row)
        except (frappe.PermissionError, frappe.ValidationError, ValueError):
            set_outcome(name,'Rejected','Subscription, ticket or endpoint is no longer permitted')
        except Exception:
            defer(row)
        finally:
            outgoing_notification.reset(token)
            frappe.set_user(actor)
        frappe.db.commit()


def recover():
    now = frappe.utils.now_datetime()
    rows = frappe.get_all('Relay Ticket Notification', filters={'status':'Pending'},
        or_filters=[['next_attempt', 'is', 'not set'], ['next_attempt', '<=', now]],
        pluck='name', order_by='creation asc', limit_page_length=30)
    for name in rows:
        try:
            dispatch(name)
        except Exception:
            frappe.db.rollback()
