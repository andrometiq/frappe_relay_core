"""Server-side Relay authorization. Never trust role names supplied by a client."""
MANAGER = 'Relay Communication Manager'
USER = 'Relay Communication User'


def internal_record_permission(doc=None, user=None, permission_type=None):
    import frappe
    user = user or frappe.session.user
    return user == 'Administrator'


def internal_record_query(user=None):
    return '' if internal_record_permission(user=user) else '1=0'


def readable_contact(name):
    """A Relay label alone never grants access to a business conversation."""
    import frappe
    relay = frappe.get_doc('Relay Contact', name); relay.check_permission('read')
    if not assignment_allowed(name) or not contact_business_allowed(relay):
        frappe.throw('Business conversation is not accessible', frappe.PermissionError)
    return relay, frappe.get_doc('Contact', relay.contact)


def contact_business_allowed(relay, user=None):
    import frappe
    user = user or frappe.session.user
    if user == 'Administrator': return True
    try:
        person = frappe.get_doc('Contact', relay.contact)
        if not person.has_permission('read', user=user) or not 1 <= len(person.links) <= 50:
            return False
        from relay_core.business_access import candidates
        return any(frappe.get_doc(*target).has_permission('read', user=user)
                   for target in candidates(relay.name))
    except frappe.DoesNotExistError:
        return False


def require_administrator():
    import frappe
    if frappe.session.user != 'Administrator':
        frappe.throw('Account-wide operations require Administrator', frappe.PermissionError)


def require_access(*, configure=False, manage=False):
    import frappe
    roles = set(frappe.get_roles(frappe.session.user))
    allowed = {'System Manager'} if configure else {'System Manager', MANAGER}
    if not configure and not manage:
        allowed.add(USER)
    if not roles.intersection(allowed):
        frappe.throw('Not permitted', frappe.PermissionError)


def install_roles():
    """Run through the app installer, never from a public endpoint."""
    import frappe
    for name in (MANAGER, USER, 'Relay Hub Service'):
        if not frappe.db.exists('Role', name):
            frappe.get_doc({'doctype': 'Role', 'role_name': name, 'desk_access': 0 if name == 'Relay Hub Service' else 1}).insert()


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
    frappe.db.add_index('Relay Message', ['relay_contact', 'name'], 'relay_contact_history')
    frappe.db.add_index('Relay Message', ['relay_contact', 'channel', 'name'], 'relay_channel_history')
    frappe.db.add_index('Relay Message', ['conversation_key', 'name'], 'relay_conversation_history')
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


def assignment_allowed(contact, user=None):
    import frappe
    user = user or frappe.session.user
    if user == 'Administrator' or set(frappe.get_roles(user)).intersection({'System Manager', MANAGER}):
        return True
    if USER not in frappe.get_roles(user):
        return False
    from relay_core.business_groups import responsible
    if responsible(contact,user):return True
    row = frappe.db.get_value('Relay Conversation Assignment', {'relay_contact':contact}, ['team','assigned_to'], as_dict=True)
    if not row: return False
    if row.assigned_to: return row.assigned_to == user
    return bool(row.team and frappe.db.exists('Relay Team Member', {'parent':row.team, 'parenttype':'Relay Team','user':user}))


def contact_permission(doc, user=None, permission_type=None):
    return assignment_allowed(doc.name, user) and contact_business_allowed(doc, user)


def message_permission(doc, user=None, permission_type=None):
    from relay_core.business_access import allowed
    return assignment_allowed(doc.relay_contact, user) and allowed(doc,user)


def assignment_condition(user=None, *, message=False):
    import frappe
    user = user or frappe.session.user
    roles=set(frappe.get_roles(user))
    if user=='Administrator' or roles.intersection({'System Manager',MANAGER}): return ''
    if USER not in roles: return '1=0'
    contact='`tabRelay Message`.relay_contact' if message else '`tabRelay Contact`.name'
    quoted=frappe.db.escape(user)
    direct=f"""{contact} IN (SELECT a.relay_contact FROM `tabRelay Conversation Assignment` a
        WHERE a.assigned_to={quoted} OR (COALESCE(a.assigned_to,'')='' AND a.team IN
        (SELECT m.parent FROM `tabRelay Team Member` m WHERE m.parenttype='Relay Team' AND m.user={quoted})))"""
    from relay_core.business_groups import responsibility_condition
    return '('+direct+' OR '+responsibility_condition(user,contact)+')'


def contact_query(user=None):
    import frappe
    user = user or frappe.session.user
    if user == 'Administrator': return ''
    people = frappe.qb.get_query('Contact', fields=['name'], ignore_permissions=False,
                                user=user, order_by='').get_sql()
    clauses = []
    for dt in frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'):
        if not frappe.has_permission(dt, 'read', user=user): continue
        business = frappe.qb.get_query(dt, fields=['name'], ignore_permissions=False,
                                      user=user, order_by='').get_sql()
        clauses.append(f"(l.link_doctype={frappe.db.escape(dt)} AND l.link_name IN ({business}))")
    scope = ' OR '.join(clauses) or '1=0'
    return f"""({assignment_condition(user) or '1=1'}) AND `tabRelay Contact`.contact IN ({people})
        AND (SELECT COUNT(*) FROM `tabDynamic Link` x WHERE x.parent=`tabRelay Contact`.contact
             AND x.parenttype='Contact' AND x.parentfield='links') BETWEEN 1 AND 50
        AND EXISTS (SELECT 1 FROM `tabDynamic Link` l WHERE l.parent=`tabRelay Contact`.contact
                    AND l.parenttype='Contact' AND l.parentfield='links' AND ({scope}))"""

def message_query(user=None):
    from relay_core.business_access import query_condition
    assignment=assignment_condition(user,message=True)
    business=query_condition(user)
    return '('+assignment+') AND '+business if assignment else business


def require_business_assignment(contact):
    import frappe
    roles=set(frappe.get_roles())
    if frappe.session.user=='Administrator' or roles.intersection({'System Manager',MANAGER}): return
    relay=frappe.db.get_value('Relay Contact',{'contact':contact},'name')
    if not relay or not assignment_allowed(relay):
        frappe.throw('This business contact is not assigned to you',frappe.PermissionError)


def has_app_permission():
    import frappe
    return frappe.session.user != 'Guest' and bool(set(frappe.get_roles()).intersection({'System Manager',MANAGER,USER}))


def can_read_contact_as(name,user):
    """Check a collaboration recipient without impersonating or granting access."""
    import frappe
    if not frappe.db.get_value('User',user,'enabled'):return False
    relay = frappe.get_doc('Relay Contact', name)
    return (assignment_allowed(name, user) and contact_business_allowed(relay, user)
            and relay.has_permission('read', user=user))


def company_allowed(company, user=None):
    """Company keys are snapshots, but still require current query/document access."""
    import frappe
    user = user or frappe.session.user
    if not company or not frappe.has_permission('Company', 'read', user=user):
        return False
    query = frappe.qb.get_query('Company', filters={'name': company}, fields=['name'],
                                ignore_permissions=False, user=user, limit=1)
    return bool(query.run()) and frappe.get_doc('Company', company).has_permission('read', user=user)


def company_condition(doctype, user=None):
    import frappe
    user = user or frappe.session.user
    if user == 'Administrator':
        return '1=1'
    table = '`tab' + doctype + '`'
    legacy = f"COALESCE({table}.company,'')=''"
    if not frappe.has_permission('Company', 'read', user=user):
        return legacy
    companies = frappe.qb.get_query('Company', fields=['name'], ignore_permissions=False,
                                    user=user, order_by='').get_sql()
    # Existing manual tickets predate company snapshots.
    return f"({legacy} OR {table}.company IN ({companies}))"
