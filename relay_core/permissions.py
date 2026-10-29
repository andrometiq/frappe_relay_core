"""Server-side Relay authorization. DocPerm decides DocType access; one row rule decides conversations."""
USER = 'Relay Communication User'
TEAM_USER = 'Relay Communication Team User'
MANAGER = 'Relay Communication Manager'
HUB_SERVICE = 'Relay Hub Service'
# Legacy team endpoints retain these roles; business access is owned by business_access.
ALL_TEAMS_ROLES = frozenset({TEAM_USER, MANAGER, 'System Manager'})


def sees_all_teams(user=None):
    import frappe
    user = user or frappe.session.user
    return user == 'Administrator' or bool(ALL_TEAMS_ROLES.intersection(frappe.get_roles(user)))


def readable_contact(name):
    """Relay roles decide who sees a conversation; the Frappe Contact is read for its name only."""
    import frappe
    relay = frappe.get_doc('Relay Contact', name); relay.check_permission('read')
    return relay, frappe.get_doc('Contact', relay.contact)


def require_administrator():
    import frappe
    if frappe.session.user != 'Administrator':
        frappe.throw('Account-wide operations require Administrator', frappe.PermissionError)


def can_manage(user=None):
    import frappe
    user = user or frappe.session.user
    return user == 'Administrator' or bool({MANAGER, 'System Manager'}.intersection(frappe.get_roles(user)))


def can_configure(user=None):
    import frappe
    return frappe.has_permission('Relay Settings', 'write', user=user)


def require_access(doctype='Relay Contact', ptype='read', *, configure=False, manage=False):
    """Check DocPerm on a DocType. manage and configure name the Relay Team and Relay Settings rights."""
    import frappe
    if configure:
        doctype, ptype = 'Relay Settings', 'write'
    elif manage:
        doctype, ptype = 'Relay Team', 'write'
    if not frappe.has_permission(doctype, ptype):
        frappe.throw('Not permitted', frappe.PermissionError)
    if (manage or doctype in ('Relay Campaign', 'Relay Campaign Recipient')) and not can_manage():
        frappe.throw('Only communication managers can perform this action', frappe.PermissionError)


def install_roles():
    """Run through the app installer, never from a public endpoint."""
    import frappe
    for name in (USER, TEAM_USER, MANAGER, HUB_SERVICE):
        if not frappe.db.exists('Role', name):
            frappe.get_doc({'doctype': 'Role', 'role_name': name, 'desk_access': 0 if name == HUB_SERVICE else 1}).insert()


def sequential_name(kind):
    """Frappe series uses a transaction-locked counter, not a random hash."""
    from frappe.model.naming import make_autoname
    prefixes = {'message': 'RELAY-MSG-', 'contact': 'RELAY-CON-', 'channel': 'RELAY-CH-'}
    return make_autoname(prefixes[kind] + '.##########')


def after_migrate():
    import frappe
    install_roles()
    from relay_core.timeline import install_indexes
    install_indexes()
    from relay_core.ai.memory import install_indexes as install_memory_indexes
    install_memory_indexes()
    frappe.db.add_index('Relay Message', ['relay_contact', 'name'], 'relay_contact_history')
    frappe.db.add_index('Relay Message', ['relay_contact', 'channel', 'name'], 'relay_channel_history')
    frappe.db.add_index('Relay Message', ['conversation_key', 'name'], 'relay_conversation_history')
    frappe.db.add_index('Relay Message', ['sender_endpoint', 'name'], 'relay_endpoint_history')
    frappe.db.add_index('Relay Flow Event', ['status','name'], 'relay_flow_pending')
    frappe.db.add_index('Relay Flow Event', ['conversation_key','status','name'], 'relay_flow_order')
    frappe.db.add_index('Relay Flow Run', ['conversation_key','status','name'], 'relay_flow_active')
    frappe.db.add_index('Relay Call', ['relay_contact','name'], 'relay_contact_calls')
    frappe.db.add_index('Relay Telegram Topic', ['channel','chat_id','name'], 'relay_telegram_topic_directory')
    frappe.db.add_index('Relay Message Action', ['owner','status','name'], 'relay_sender_pending')
    frappe.db.add_index('Relay Message Action', ['status','modified','name'], 'relay_action_recovery')
    frappe.db.add_index('Relay Message Translation', ['message','source_hash'], 'relay_translation_source')
    frappe.db.add_index('Relay Message Translation', ['status','modified'], 'relay_translation_recovery')
    frappe.db.add_index('Relay Delivery Receipt', ['message','name'], 'relay_participant_receipts')
    frappe.db.add_index('Relay Canned Reply', ['channel','published','title','name'], 'relay_saved_reply_directory')
    frappe.db.add_index('Relay Conversation State', ['last_read','relay_contact'], 'relay_reader_cursors')
    frappe.db.add_index('Relay Business Conversation State', ['business_doctype','business_name','user'], 'relay_business_state')
    frappe.db.add_index('Relay Business Conversation State', ['last_read','user'], 'relay_business_readers')
    frappe.db.add_index('Relay Message Read', ['message','user'], 'relay_message_readers')
    frappe.db.add_index('Relay Message Read', ['user','message'], 'relay_user_reads')
    frappe.db.add_index('Relay Internal Comment', ['relay_contact','name'], 'relay_comment_history')
    frappe.db.add_index('Relay Notification', ['user','name'], 'relay_user_notifications')
    frappe.db.add_index('Relay Campaign Recipient', ['campaign','status','name'], 'relay_campaign_pending')
    frappe.db.add_index('Relay Ticket Notification', ['status','next_attempt'], 'relay_ticket_pending')
    frappe.db.add_index('Relay Hub Event', ['projection_status','name'], 'relay_event_projection')
    from relay_core.relay_chats import install_index as install_chat_index
    install_chat_index()
    from relay_core.ticket_settings import seed_defaults
    seed_defaults()


def assignment_allowed(contact, user=None):
    """A conversation follows its Contact's configured business types."""
    import frappe
    from relay_core.business_access import person_allowed
    person = frappe.db.get_value('Relay Contact', contact, 'contact')
    return bool(person and person_allowed(person, user))


def contact_permission(doc, user=None, permission_type=None):
    return assignment_allowed(doc.name, user)


def message_permission(doc, user=None, permission_type=None):
    from relay_core.business_access import message_allowed
    return assignment_allowed(doc.relay_contact, user) and message_allowed(doc,user)


def assignment_condition(user=None, *, message=False):
    """SQL twin of assignment_allowed, shared by inbox and message queries."""
    from relay_core.business_access import person_condition
    if message:
        return ('`tabRelay Message`.relay_contact IN (SELECT name FROM `tabRelay Contact` WHERE '
                + person_condition('`tabRelay Contact`.contact', user) + ')')
    return person_condition('`tabRelay Contact`.contact', user)


def contact_query(user=None):
    return assignment_condition(user)


def message_query(user=None):
    """Messages of visible conversations. Triage messages stay hidden from everyone but Administrator."""
    import frappe
    if (user or frappe.session.user) == 'Administrator': return ''
    from relay_core.business_access import message_condition
    assignment = assignment_condition(user, message=True)
    business = message_condition(user)
    return f"({assignment}) AND COALESCE(`tabRelay Message`.legacy_triage,0)=0 AND ({business})"


def require_business_assignment(contact):
    import frappe
    relay=frappe.db.get_value('Relay Contact',{'contact':contact},'name')
    if not relay or not assignment_allowed(relay):
        frappe.throw('This business contact is not assigned to you',frappe.PermissionError)


def has_app_permission():
    import frappe
    return frappe.session.user != 'Guest' and frappe.has_permission('Relay Contact', 'read')


def can_read_contact_as(name,user):
    """Check a collaboration recipient without impersonating or granting access."""
    import frappe
    if not frappe.db.get_value('User',user,'enabled'):return False
    return bool(frappe.get_doc('Relay Contact', name).has_permission('read', user=user))


def has_companies():
    """Sites without a Company DocType (no ERPNext) are one company: records keep an empty company."""
    import frappe
    return bool(frappe.db.exists('DocType', 'Company'))


def company_allowed(company, user=None):
    """Company keys are snapshots, but still require current query/document access."""
    import frappe
    user = user or frappe.session.user
    if not has_companies():
        return not company
    if not company or not frappe.has_permission('Company', 'read', user=user):
        return False
    query = frappe.qb.get_query('Company', filters={'name': company}, fields=['name'],
                                ignore_permissions=False, user=user, limit=1)
    return bool(query.run()) and frappe.permissions.has_permission('Company', 'read', frappe.get_doc('Company', company),
                                                                   user=user, print_logs=False)


def company_condition(doctype, user=None):
    import frappe
    user = user or frappe.session.user
    if user == 'Administrator':
        return '1=1'
    table = '`tab' + doctype + '`'
    legacy = f"COALESCE({table}.company,'')=''"
    if not has_companies() or not frappe.has_permission('Company', 'read', user=user):
        return legacy
    companies = frappe.qb.get_query('Company', fields=['name'], ignore_permissions=False,
                                    user=user, order_by='').get_sql()
    # Existing manual tickets predate company snapshots.
    return f"({legacy} OR {table}.company IN ({companies}))"
