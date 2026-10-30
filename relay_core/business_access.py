"""Message business ownership is distinct from contact membership."""
import json
import frappe
import frappe.permissions


def allowed_types(user=None):
    """The Relay business access rule. Desk permissions and teams do not grant access."""
    from relay_core.permissions import USER, MANAGER
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    if user != 'Administrator' and not roles.intersection({USER, MANAGER, 'System Manager'}):
        return set()
    enabled = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    if user == 'Administrator' or roles.intersection({MANAGER, 'System Manager'}):
        return enabled
    assigned = frappe.get_all('Relay Contact Type User', filters={
        'user': user, 'parenttype': 'Relay Contact Type', 'parentfield': 'users'}, pluck='parent')
    return enabled.intersection(assigned)


def relay_user(user=None):
    from relay_core.permissions import USER, MANAGER
    user = user or frappe.session.user
    return user == 'Administrator' or bool(set(frappe.get_roles(user)).intersection({USER, MANAGER, 'System Manager'}))


def require_type(doctype, user=None):
    if not isinstance(doctype, str) or doctype not in allowed_types(user):
        frappe.throw('Business type is not accessible', frappe.PermissionError)


def document_name(value):
    """Reject filter selectors before Frappe can resolve them to a document."""
    if not isinstance(value, str) or not value.strip() or len(value) > 140 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        frappe.throw('Choose a document name of at most 140 printable characters')
    return value


def business_document(doctype, name, user=None):
    require_type(doctype, user)
    return frappe.get_doc(doctype, document_name(name))


def person_condition(expression, user=None):
    """Contact membership, applied before pagination and counts; unlinked people are shared."""
    if not relay_user(user):
        return '1=0'
    types = ', '.join(frappe.db.escape(dt) for dt in sorted(allowed_types(user))) or "''"
    links = (f"SELECT 1 FROM `tabDynamic Link` l WHERE l.parent={expression} "
             "AND l.parenttype='Contact' AND l.parentfield='links'")
    return f"(NOT EXISTS ({links}) OR EXISTS ({links} AND l.link_doctype IN ({types})))"


def unlinked_contact(contact):
    """No Contact business links at all, including types not configured in Relay."""
    person = frappe.db.get_value('Relay Contact', contact, 'contact')
    return not person or not frappe.db.exists('Dynamic Link', {
        'parent': person, 'parenttype': 'Contact', 'parentfield': 'links'})


def person_allowed(name, user=None):
    return bool(frappe.db.sql(f"SELECT 1 FROM `tabContact` WHERE name=%s AND {person_condition('`tabContact`.name', user)}", name))


def require_person(name, user=None):
    document_name(name)
    if not person_allowed(name, user):
        frappe.throw('Contact is not accessible', frappe.PermissionError)


def people_query(**kwargs):
    """Relay-scoped Contact reads without changing Contact's Desk permissions."""
    from pypika.terms import LiteralValue
    return frappe.qb.get_query('Contact', ignore_permissions=True, **kwargs).where(
        LiteralValue(person_condition('`tabContact`.name')))


def scoped_document(doctype, name, filters, fields=()):
    """Read one name through query hooks, then recheck fixed scope and fields."""
    document_name(name)
    from frappe_tools.ai.tools import get_readable_meta, get_readable_columns
    meta = get_readable_meta(doctype)
    required = set(fields) | set(filters)
    if not required.issubset(get_readable_columns(meta)):
        raise ValueError('Unreadable scope or result fields')
    if 'name' in filters and filters['name'] != name:
        raise ValueError('Document is outside the selected scope')
    if not frappe.get_list(doctype, filters=dict(filters, name=name), fields=['name'], page_length=1):
        raise ValueError('No readable scoped document')
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    if any(doc.get(key) != value for key, value in filters.items()):
        raise ValueError('Document scope changed')
    if not required.issubset(get_readable_columns(meta)):
        raise ValueError('Field access changed')
    doc.apply_fieldlevel_read_permissions()
    if any(doc.get(key) != value for key, value in filters.items()):
        raise ValueError('Document scope is not readable')
    return doc


MAX_LINKS = 50


def candidates(contact):
    """Enabled business links whose records exist. A Contact with more than MAX_LINKS links of any type has none."""
    person=frappe.db.get_value('Relay Contact',contact,'contact')
    if not person:return []
    enabled=set(frappe.get_all('Relay Contact Type',filters={'enabled':1},pluck='business_doctype'))
    rows=frappe.get_all('Dynamic Link',filters={'parent':person,'parenttype':'Contact','parentfield':'links'},fields=['link_doctype','link_name'],limit_page_length=MAX_LINKS+1)
    if len(rows)>MAX_LINKS:return []
    return sorted({(r.link_doctype,r.link_name) for r in rows if r.link_doctype in enabled and frappe.db.exists(r.link_doctype, r.link_name)})


def primary(contact, links=None):
    """The marked link, or the only link. A primary whose Contact link is gone does not count."""
    if links is None: links = candidates(contact)
    if len(links) == 1: return links[0]
    marked = frappe.db.get_value('Relay Contact', contact, ['primary_doctype', 'primary_name'])
    return tuple(marked) if marked and tuple(marked) in links else None


def primary_sql(doctype_value):
    """SQL twin of `primary` for one business type: (relay_contact, business_name) rows. `doctype_value` is a bound
    parameter. The link's own record must exist; the other links are counted without that check."""
    links = ("FROM `tabDynamic Link` x WHERE x.parent=r.contact AND x.parenttype='Contact' AND x.parentfield='links'")
    enabled = links.replace('WHERE', "JOIN `tabRelay Contact Type` t ON t.business_doctype=x.link_doctype AND t.enabled=1 WHERE")
    return f"""SELECT DISTINCT r.name AS relay_contact, l.link_name AS business_name FROM `tabRelay Contact` r
        JOIN `tabDynamic Link` l ON l.parent=r.contact AND l.parenttype='Contact' AND l.parentfield='links'
            AND l.link_doctype={doctype_value}
        WHERE (SELECT COUNT(*) {links})<={MAX_LINKS}
            AND ((r.primary_doctype=l.link_doctype AND r.primary_name=l.link_name)
                 OR NOT EXISTS (SELECT 1 {enabled} AND (x.link_doctype<>l.link_doctype OR x.link_name<>l.link_name)))"""


def primary_record(contact, links=None):
    """The primary record the current user can read, for a conversation header."""
    target = primary(contact, links)
    if not target: return None
    if target[0] not in allowed_types(): return None
    doc = frappe.get_doc(*target)
    from relay_core.business_groups import title_field
    title = doc.get(title_field(target[0]))
    return {'doctype': target[0], 'name': target[1], 'title': str(title or target[1])}


def preserve_primary_history(contact, *, authorize=False):
    """Freeze inherited message ownership before changing a primary or its links."""
    frappe.db.get_value('Relay Contact', contact, 'name', for_update=True)
    current = primary(contact)
    if not current:
        return
    if authorize:
        business_document(*current)
    frappe.db.sql("""UPDATE `tabRelay Message` SET business_doctype=%s, business_name=%s
        WHERE relay_contact=%s AND COALESCE(business_doctype, '')='' AND COALESCE(business_name, '')=''
        AND COALESCE(legacy_triage, 0)=0""", (*current, contact))


def drop_stale_primary(contact):
    marked = frappe.db.get_value('Relay Contact', contact, ['primary_doctype', 'primary_name'])
    if marked and any(marked) and tuple(marked) not in candidates(contact):
        frappe.db.set_value('Relay Contact', contact, {'primary_doctype': None, 'primary_name': None})


def reference(doc):
    if doc.get('legacy_triage'): return None
    if doc.get('business_doctype') and doc.get('business_name'):
        return doc.business_doctype,doc.business_name
    return primary(doc.relay_contact)


def message_allowed(doc, user=None):
    """A message is readable through its business, or through its contact's one conversation."""
    if doc.get('legacy_triage'): return (user or frappe.session.user) == 'Administrator'
    if reference(doc): return allowed(doc, user)
    from relay_core.permissions import assignment_allowed
    return assignment_allowed(doc.relay_contact, user)


def allowed(doc, user=None):
    if doc.get('legacy_triage'): return (user or frappe.session.user) == 'Administrator'
    target = reference(doc)
    if not target or target[0] not in allowed_types(user): return False
    if (doc.get('doctype') != 'Relay Ticket' and not doc.get('ticket_notification')
            and target not in candidates(doc.relay_contact)): return False
    return bool(frappe.db.exists(*target))


def associate(doc,method=None):
    from relay_core.ticket_notifications import message_ownership
    notification = doc.direction == 'Outgoing' and message_ownership.get() == (doc.relay_contact, doc.channel,
        doc.sender_endpoint, doc.business_doctype, doc.business_name, doc.get('ticket_notification'))
    if doc.get('ticket_notification') and not notification:
        frappe.throw('Only a validated ticket notification may cross contact business links')
    if doc.get('business_doctype') or doc.get('business_name'):
        if notification:
            return
        if (doc.get('business_doctype'),doc.get('business_name')) not in candidates(doc.relay_contact):
            frappe.throw('Message business must be linked to its contact')
        return
    target=reference(doc)
    if target:doc.business_doctype,doc.business_name=target


def incoming_reference(contact, channel, endpoint, context, links=None):
    if links is None: links = candidates(contact)
    if context.get('provider') == 'Email':
        return email_reference(contact, channel, endpoint, context, links)
    reply = context.get('reply_to_message_id')
    if reply:
        from relay_core.message_updates import provider_key
        from relay_core.automation.provenance import conversation_key
        target = frappe.db.get_value('Relay Message',
            {'provider_message_key': provider_key(channel, endpoint, reply), 'relay_contact': contact,
             'channel': channel, 'sender_endpoint': endpoint,
             'conversation_key': conversation_key(channel, endpoint, context)},
            ['business_doctype', 'business_name'], as_dict=True)
        if target and (target.business_doctype, target.business_name) in links:
            context['business_rule'] = 'reply_context'
            return target.business_doctype, target.business_name
        if target and not target.business_doctype and campaign_send(channel, endpoint, reply):
            return None  # A campaign send names no business; the sender's links decide.
        if target:
            context['business_rule'] = 'triage_unlinked_reference'
    return None


def campaign_send(channel, endpoint, reply):
    """The reply quotes a bulk campaign send to this number. Hub reports provider IDs in
    windows, so a sent row whose ID has not arrived yet also counts."""
    return bool(frappe.db.sql('''SELECT 1 FROM `tabRelay Campaign Recipient` r JOIN `tabRelay Campaign` c ON c.name=r.campaign
        WHERE c.channel=%(channel)s AND r.destination=%(endpoint)s
        AND (r.provider_id=%(reply)s OR (r.attempted=1 AND IFNULL(r.provider_id, '')='')) LIMIT 1''',
        dict(channel=channel, endpoint=endpoint, reply=reply)))


def email_reference(contact, channel, endpoint, context, links):
    from relay_core.message_updates import provider_key
    from relay_core.automation.provenance import context_of
    resolved = {}
    visiting = set()

    def resolve(identifier):
        if identifier in resolved:
            return resolved[identifier]
        if identifier in visiting or len(resolved) + len(visiting) >= 100:
            raise ValueError('triage_conflicting_references')
        visiting.add(identifier)
        name = frappe.db.get_value('Relay Message', {
            'provider_message_key': provider_key(channel, endpoint, identifier),
            'relay_contact': contact, 'channel': channel, 'sender_endpoint': endpoint}, 'name')
        result = None
        if name:
            doc = frappe.get_doc('Relay Message', name)
            business = reference(doc)
            if business not in links:
                raise ValueError('triage_unlinked_reference')
            parent = context_of(doc)
            thread = parent.get('email_thread_id')
            if not thread:
                ancestors = [resolve(ref) for ref in ancestry(parent)]
                ancestors = [row for row in ancestors if row]
                if any(row[0] != business for row in ancestors) or len({row[1] for row in ancestors}) > 1:
                    raise ValueError('triage_conflicting_references')
                thread = ancestors[0][1] if ancestors else parent.get('message_id') or identifier
            result = business, thread
        visiting.remove(identifier)
        resolved[identifier] = result
        return result

    def ancestry(value):
        return list(dict.fromkeys(filter(None, [value.get('reply_to_message_id') or value.get('in_reply_to'),
                                                *reversed(value.get('references', []))])))

    matches = []
    threads = set()
    try:
        for parent in ancestry(context):
            result = resolve(parent)
            if result:
                matches.append(result[0])
                threads.add(result[1])
            for prompt in email_prompt_contexts(contact, channel, endpoint, parent):
                threads.add(prompt.get('email_thread_id') or prompt.get('message_id'))
    except ValueError as exc:
        context['business_rule'] = str(exc)
        return None
    threads.discard(None)
    if len(threads) > 1 or len(set(matches)) > 1:
        context['business_rule'] = 'triage_conflicting_references'
        return None
    if threads:
        context['email_thread_id'] = next(iter(threads))
    if matches:
        context['business_rule'] = 'reply_context'
        return matches[0]
    return None


def email_prompt_contexts(contact, channel, endpoint, message_id):
    """Prompts are journaled actions, scoped to the same verified sender/thread."""
    from relay_core.automation.provenance import conversation_key
    rows = frappe.db.sql("""
        SELECT a.payload, r.conversation_key FROM `tabRelay Message Action` a
        JOIN `tabRelay Business Routing` r ON r.prompt_action=a.name
        WHERE a.operation='business_prompt' AND a.status='Submitted'
          AND a.start_contact=%s AND a.target_channel=%s
          AND r.relay_contact=%s AND r.channel=%s AND r.endpoint=%s
          AND JSON_UNQUOTE(JSON_EXTRACT(a.result, '$.message_id'))=%s
    """, (contact, channel, contact, channel, endpoint, message_id), as_dict=True)
    for row in rows:
        payload = json.loads(row.payload)
        context = payload.get('context') or {}
        if (context.get('provider') == 'Email' and payload.get('routing') == row.conversation_key
                and conversation_key(channel, endpoint, context) == row.conversation_key):
            yield context


def linked_business(contact, doctype=None, name=None):
    """The named business link of the contact, or else its primary one."""
    links = candidates(contact)
    business = (doctype, name) if doctype or name else primary(contact, links)
    if business not in links:
        frappe.throw('Choose a linked business record')
    return business


def choose_business(contact, doctype=None, name=None):
    business = linked_business(contact, doctype, name)
    business_document(*business)
    return business


def action_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    if user == 'Administrator':
        return True
    if doc.owner != user:
        return False
    payload = json.loads(doc.payload or '{}') if isinstance(doc.payload, str) else doc.payload or {}
    business = payload.get('business') or [payload.get('start', {}).get(key) for key in ('business_doctype', 'business_name')]
    if not all(business):
        if not any(business) and payload.get('start') and doc.get('start_contact'):
            return unlinked_start(doc.start_contact, user)
        # Only pre-snapshot, source-anchored actions can inherit ownership.
        if any(business) or not doc.get('source_message'):
            return False
        try:
            source = frappe.get_doc('Relay Message', doc.source_message)
            return bool(reference(source) and source.has_permission('read', user=user))
        except frappe.DoesNotExistError:
            return False
    try:
        return business[0] in allowed_types(user) and bool(frappe.db.exists(*business))
    except frappe.DoesNotExistError:
        return False


def action_query(user=None):
    user = user or frappe.session.user
    if user == 'Administrator':
        return ''
    table = '`tabRelay Message Action`'
    fields = [f"COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT({table}.payload, '$.business[{index}]')), 'null'), "
              f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT({table}.payload, '$.start.{key}')), 'null'))"
              for index, key in enumerate(('business_doctype', 'business_name'))]
    clauses = []
    for dt in sorted(allowed_types(user)):
        query = frappe.qb.get_query(dt, fields=['name'], ignore_permissions=True, order_by='').get_sql()
        clauses.append(f'({fields[0]}={frappe.db.escape(dt)} AND {fields[1]} IN ({query}))')
    scope = ' OR '.join(clauses) or '1=0'
    sources = frappe.qb.get_query('Relay Message', fields=['name'], ignore_permissions=False,
                                  user=user, order_by='').get_sql()
    # Triage records never provide legacy action ownership, even to managers.
    legacy = (f"COALESCE({fields[0]}, '')='' AND COALESCE({fields[1]}, '')='' "
              f"AND {table}.source_message IN (SELECT name FROM `tabRelay Message` "
              f"WHERE COALESCE(legacy_triage,0)=0 AND name IN ({sources}))")
    contacts = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False,
                                   user=user, order_by='').get_sql()
    unlinked = (f"COALESCE({fields[0]}, '')='' AND COALESCE({fields[1]}, '')='' "
                f"AND JSON_EXTRACT({table}.payload, '$.start') IS NOT NULL AND {table}.start_contact IN ({contacts})")
    return f'{table}.owner={frappe.db.escape(user)} AND ({scope} OR ({legacy}) OR ({unlinked}))'


def unlinked_start(contact, user):
    """A chat started with a contact that has no records belongs to whoever can read the contact."""
    try:
        return frappe.get_doc('Relay Contact', contact).has_permission('read', user=user) and not candidates(contact)
    except frappe.DoesNotExistError:
        return False


def explicit_condition(doctype, user=None, *, allow_empty=False):
    user = user or frappe.session.user
    table = '`tab' + doctype + '`'
    clauses = []
    for dt in sorted(allowed_types(user)):
        query = frappe.qb.get_query(dt, fields=['name'], ignore_permissions=True, order_by='').get_sql()
        clauses.append(f'({table}.business_doctype={frappe.db.escape(dt)} AND {table}.business_name IN ({query}))')
    if allow_empty and relay_user(user):
        clauses.append(f"(COALESCE({table}.business_doctype,'')='' AND COALESCE({table}.business_name,'')='')")
    return '(' + ' OR '.join(clauses) + ')' if clauses else '1=0'


def message_condition(user=None):
    """Business ownership for message queries, including unstamped primary history."""
    table = '`tabRelay Message`'
    explicit = explicit_condition('Relay Message', user)
    linked = (f"EXISTS (SELECT 1 FROM `tabRelay Contact` r JOIN `tabDynamic Link` l ON l.parent=r.contact "
              f"WHERE r.name={table}.relay_contact AND l.parenttype='Contact' AND l.parentfield='links' "
              f"AND l.link_doctype={table}.business_doctype AND l.link_name={table}.business_name)")
    types = ', '.join(frappe.db.escape(dt) for dt in sorted(allowed_types(user))) or "''"
    # A valid marked primary owns unstamped history. Do not let another link expose it.
    private_primary = (f"EXISTS (SELECT 1 FROM `tabRelay Contact` r JOIN `tabDynamic Link` l ON l.parent=r.contact "
                       "JOIN `tabRelay Contact Type` t ON t.business_doctype=l.link_doctype AND t.enabled=1 "
                       f"WHERE r.name={table}.relay_contact AND l.parenttype='Contact' AND l.parentfield='links' "
                       "AND l.link_doctype=r.primary_doctype AND l.link_name=r.primary_name "
                       f"AND l.link_doctype NOT IN ({types}))")
    return (f"(({explicit}) AND (COALESCE({table}.ticket_notification,'')!='' OR {linked})) OR "
            f"(COALESCE({table}.business_doctype,'')='' AND COALESCE({table}.business_name,'')='' "
            f"AND NOT {private_primary})")


def readable_business(doc, user=None):
    from relay_core.permissions import readable_contact, can_read_contact_as
    if user is None:
        readable_contact(doc.relay_contact)
    elif not can_read_contact_as(doc.relay_contact, user):
        frappe.throw('Conversation is not accessible', frappe.PermissionError)
    if not allowed(doc, user):
        frappe.throw('Business record is not accessible', frappe.PermissionError)
    return reference(doc)
