"""Message business ownership is distinct from contact membership."""
import json
import frappe


def scoped_document(doctype, name, filters, fields=()):
    """Read one name through query hooks, then recheck fixed scope and fields."""
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


def candidates(contact):
    person=frappe.db.get_value('Relay Contact',contact,'contact')
    if not person:return []
    enabled=set(frappe.get_all('Relay Contact Type',filters={'enabled':1},pluck='business_doctype'))
    rows=frappe.get_all('Dynamic Link',filters={'parent':person,'parenttype':'Contact','parentfield':'links'},fields=['link_doctype','link_name'],limit_page_length=51)
    if len(rows)>50:return []
    return sorted({(r.link_doctype,r.link_name) for r in rows if r.link_doctype in enabled and frappe.db.exists(r.link_doctype, r.link_name)})


def reference(doc):
    if doc.get('legacy_triage'): return None
    if doc.get('business_doctype') and doc.get('business_name'):
        return doc.business_doctype,doc.business_name
    links=candidates(doc.relay_contact)
    return links[0] if len(links)==1 else None


def allowed(doc,user=None):
    if (user or frappe.session.user) == 'Administrator': return True
    if doc.get('legacy_triage'): return False
    target=reference(doc)
    if not target:return False
    # A removed Contact link ends access to that business's history at once; a validated
    # ticket notification is the one stored exception, as it reaches a subscriber's own contact.
    if not doc.get('ticket_notification') and target not in candidates(doc.relay_contact):return False
    try:return frappe.get_doc(*target).has_permission('read',user=user)
    except frappe.DoesNotExistError:return False


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


def query_condition(user=None):
    # Business permission conditions belong inside the query, before pagination.
    user=user or frappe.session.user
    if user == 'Administrator': return ''
    clauses=[]
    for dt in frappe.get_all('Relay Contact Type',filters={'enabled':1},pluck='business_doctype',limit_page_length=200):
        if not frappe.has_permission(dt,'read',user=user):continue
        query=frappe.qb.get_query(dt,fields=['name'],ignore_permissions=False,user=user,order_by='')
        subquery=query.get_sql()
        value=frappe.db.escape(dt)
        explicit=f"""(`tabRelay Message`.business_doctype={value} AND `tabRelay Message`.business_name IN ({subquery})
        AND (COALESCE(`tabRelay Message`.ticket_notification,'')!='' OR EXISTS (SELECT 1 FROM `tabRelay Contact` c JOIN `tabDynamic Link` k ON k.parent=c.contact
         WHERE c.name=`tabRelay Message`.relay_contact AND k.parenttype='Contact' AND k.parentfield='links'
         AND k.link_doctype={value} AND k.link_name=`tabRelay Message`.business_name)))"""
        # Legacy records resolve only when there is exactly one configured business link.
        legacy=f"""(COALESCE(`tabRelay Message`.business_name,'')='' AND `tabRelay Message`.relay_contact IN
        (SELECT r.name FROM `tabRelay Contact` r JOIN `tabDynamic Link` l ON l.parent=r.contact
         WHERE l.parenttype='Contact' AND l.parentfield='links' AND l.link_doctype={value}
         AND l.link_name IN ({subquery}) AND
         (SELECT count(*) FROM `tabDynamic Link` x JOIN `tabRelay Contact Type` t ON t.business_doctype=x.link_doctype AND t.enabled=1
          WHERE x.parent=r.contact AND x.parenttype='Contact' AND x.parentfield='links')=1))"""
        clauses.append('('+explicit+' OR '+legacy+')')
    business = '(COALESCE(`tabRelay Message`.legacy_triage,0)=0 AND ('+' OR '.join(clauses)+'))' if clauses else '1=0'
    return business


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
        if target:
            context['business_rule'] = 'triage_unlinked_reference'
    return None


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


def choose_business(contact, doctype=None, name=None):
    links = candidates(contact)
    business = (doctype, name) if doctype or name else links[0] if len(links) == 1 else None
    if business not in links:
        frappe.throw('Choose a linked business record')
    frappe.get_doc(*business).check_permission('read')
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
        # Only pre-snapshot, source-anchored actions can inherit ownership.
        if any(business) or not doc.get('source_message'):
            return False
        try:
            source = frappe.get_doc('Relay Message', doc.source_message)
            return bool(reference(source) and source.has_permission('read', user=user))
        except frappe.DoesNotExistError:
            return False
    try:
        return frappe.get_doc(*business).has_permission('read', user=user)
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
    for dt in frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'):
        if not frappe.has_permission(dt, 'read', user=user):
            continue
        query = frappe.qb.get_query(dt, fields=['name'], ignore_permissions=False, user=user, order_by='').get_sql()
        clauses.append(f'({fields[0]}={frappe.db.escape(dt)} AND {fields[1]} IN ({query}))')
    scope = ' OR '.join(clauses) or '1=0'
    sources = frappe.qb.get_query('Relay Message', fields=['name'], ignore_permissions=False,
                                  user=user, order_by='').get_sql()
    # Triage records never provide legacy action ownership, even to managers.
    legacy = (f"COALESCE({fields[0]}, '')='' AND COALESCE({fields[1]}, '')='' "
              f"AND {table}.source_message IN (SELECT name FROM `tabRelay Message` "
              f"WHERE COALESCE(legacy_triage,0)=0 AND name IN ({sources}))")
    return f'{table}.owner={frappe.db.escape(user)} AND ({scope} OR ({legacy}))'


def explicit_condition(doctype, user=None, *, allow_empty=False):
    user = user or frappe.session.user
    if user == 'Administrator': return ''
    table = '`tab' + doctype + '`'
    clauses = []
    for dt in frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'):
        if not frappe.has_permission(dt, 'read', user=user): continue
        query = frappe.qb.get_query(dt, fields=['name'], ignore_permissions=False, user=user, order_by='').get_sql()
        clauses.append(f'({table}.business_doctype={frappe.db.escape(dt)} AND {table}.business_name IN ({query}))')
    if allow_empty:
        clauses.append(f"(COALESCE({table}.business_doctype,'')='' AND COALESCE({table}.business_name,'')='')")
    return '(' + ' OR '.join(clauses) + ')' if clauses else '1=0'


def readable_business(doc, user=None):
    from relay_core.permissions import readable_contact, can_read_contact_as
    if user is None:
        readable_contact(doc.relay_contact)
    elif not can_read_contact_as(doc.relay_contact, user):
        frappe.throw('Conversation is not accessible', frappe.PermissionError)
    if not allowed(doc, user):
        frappe.throw('Business record is not accessible', frappe.PermissionError)
    return reference(doc)
