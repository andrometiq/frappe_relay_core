"""Message business ownership is distinct from contact membership."""
import frappe


def candidates(contact):
    person=frappe.db.get_value('Relay Contact',contact,'contact')
    if not person:return []
    enabled=set(frappe.get_all('Relay Contact Type',filters={'enabled':1},pluck='business_doctype'))
    rows=frappe.get_all('Dynamic Link',filters={'parent':person,'parenttype':'Contact','parentfield':'links'},fields=['link_doctype','link_name'],limit_page_length=51)
    if len(rows)>50:return []
    return sorted({(r.link_doctype,r.link_name) for r in rows if r.link_doctype in enabled and frappe.db.exists(r.link_doctype, r.link_name)})


def reference(doc):
    if doc.get('business_doctype') and doc.get('business_name'):
        return doc.business_doctype,doc.business_name
    links=candidates(doc.relay_contact)
    return links[0] if len(links)==1 else None


def allowed(doc,user=None):
    target=reference(doc)
    if not target:return False
    try:return frappe.get_doc(*target).has_permission('read',user=user)
    except frappe.DoesNotExistError:return False


def associate(doc,method=None):
    if doc.get('business_doctype') or doc.get('business_name'):
        if (doc.get('business_doctype'),doc.get('business_name')) not in candidates(doc.relay_contact):
            frappe.throw('Message business must be linked to its contact')
        return
    target=reference(doc)
    if target:doc.business_doctype,doc.business_name=target


def query_condition(user=None):
    # Business permission conditions belong inside the query, before pagination.
    user=user or frappe.session.user
    clauses=[]
    for dt in frappe.get_all('Relay Contact Type',filters={'enabled':1},pluck='business_doctype',limit_page_length=200):
        if not frappe.has_permission(dt,'read',user=user):continue
        query=frappe.qb.get_query(dt,fields=['name'],ignore_permissions=False,user=user,order_by='')
        subquery=query.get_sql()
        value=frappe.db.escape(dt)
        explicit=f"(`tabRelay Message`.business_doctype={value} AND `tabRelay Message`.business_name IN ({subquery}))"
        # Legacy records resolve only when there is exactly one configured business link.
        legacy=f"""(COALESCE(`tabRelay Message`.business_name,'')='' AND `tabRelay Message`.relay_contact IN
        (SELECT r.name FROM `tabRelay Contact` r JOIN `tabDynamic Link` l ON l.parent=r.contact
         WHERE l.parenttype='Contact' AND l.parentfield='links' AND l.link_doctype={value}
         AND l.link_name IN ({subquery}) AND
         (SELECT count(*) FROM `tabDynamic Link` x JOIN `tabRelay Contact Type` t ON t.business_doctype=x.link_doctype AND t.enabled=1
          WHERE x.parent=r.contact AND x.parenttype='Contact' AND x.parentfield='links')=1))"""
        clauses.append('('+explicit+' OR '+legacy+')')
    return '('+' OR '.join(clauses)+')' if clauses else '1=0'


def incoming_reference(contact, channel, endpoint, context, links=None):
    if links is None: links = candidates(contact)
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
    return None
