"""Ticket actions shared by Desk/API; all message references checked server-side."""
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.api import validate_reference


def validate_ticket(doc, check_assignment=True):
    require_access()
    if not isinstance(doc.subject, str) or not doc.subject.strip() or len(doc.subject) > 140:
        frappe.throw('Ticket subject must contain 1–140 characters')
    if doc.brief and (not isinstance(doc.brief, str) or len(doc.brief) > 4000):
        frappe.throw('Ticket brief must contain at most 4000 characters')
    if doc.category not in ('Query', 'Payment evidence', 'Support', 'Other'):
        frappe.throw('Invalid ticket category')
    if doc.status not in ('Open', 'In progress', 'Resolved', 'Closed'):
        frappe.throw('Invalid ticket status')
    if not doc.messages or len(doc.messages) > 50:
        frappe.throw('Link between 1 and 50 messages')
    seen = set()
    for row in doc.messages:
        validate_reference(row.message, 'MSG')
        if row.message in seen:
            frappe.throw('A message can only be linked once per ticket')
        seen.add(row.message)
        message = frappe.get_doc('Relay Message', row.message)
        message.check_permission('read')
        readable_contact(message.relay_contact)
        if doc.get('business_doctype') or doc.get('business_name'):
            from relay_core.business_access import reference
            if reference(message) != (doc.get('business_doctype'), doc.get('business_name')):
                frappe.throw('Ticket business must match its conversation')
    if not check_assignment:
        return
    previous = doc.get_doc_before_save()
    if check_assignment and (doc.get('assigned_to') or '') != ((previous.get('assigned_to') or '') if previous else ''):
        require_access(manage=True)
        if doc.assigned_to:
            if not frappe.db.get_value('User', doc.assigned_to, 'enabled'):
                frappe.throw('Choose an enabled agent')
            actor = frappe.session.user
            try:
                frappe.set_user(doc.assigned_to)
                require_access()
                for row in doc.messages:
                    message = frappe.get_doc('Relay Message', row.message)
                    message.check_permission('read')
                    readable_contact(message.relay_contact)
            finally:
                frappe.set_user(actor)


@frappe.whitelist(methods=['POST'])
def create(subject, messages, brief='', category='Query'):
    require_access()
    if isinstance(messages, str):
        messages = frappe.parse_json(messages)
    if not isinstance(messages, list) or not 1 <= len(messages) <= 50 or any(not isinstance(m, str) for m in messages):
        frappe.throw('Messages must be a list of 1–50 references')
    doc = frappe.get_doc({'doctype': 'Relay Ticket', 'subject': subject, 'brief': brief,
                          'category': category, 'status': 'Open',
                          'messages': [{'message': name} for name in messages]})
    # insert runs the controller validation and Frappe create permissions.
    doc.insert()
    return {'name': doc.name, 'status': doc.status}


@frappe.whitelist(methods=['POST'])
def update_status(name, status):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name)
    doc.check_permission('write')
    doc.status = status
    doc.save()
    return {'name': doc.name, 'status': doc.status}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access()
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name)
    doc.check_permission('read')
    links = []
    for row in doc.messages:
        message = frappe.get_doc('Relay Message', row.message)
        links.append({'message': message.name, 'contact': message.relay_contact,
                      'channel': message.channel})
    return {'name': doc.name, 'subject': doc.subject, 'brief': doc.brief,
            'category': doc.category, 'status': doc.status, 'messages': links, 'creation': doc.creation,
            'assigned_to': doc.get('assigned_to'),
            'business_doctype': doc.get('business_doctype'), 'business_name': doc.get('business_name'),
            'handoff_reason': doc.get('handoff_reason'), 'source_run': doc.get('source_run'),
            'can_assign': bool(set(frappe.get_roles()).intersection({'System Manager','Relay Communication Manager'}))}


@frappe.whitelist(methods=['POST'])
def assign(name, user=''):
    require_access(manage=True)
    validate_reference(name, 'TKT')
    doc = frappe.get_doc('Relay Ticket', name)
    doc.check_permission('write')
    doc.assigned_to = user or None
    doc.save()
    return read(name)


def permission(doc, user=None, permission_type=None):
    from relay_core.permissions import can_read_contact_as
    from relay_core.business_access import allowed, reference
    user = user or frappe.session.user
    if user == 'Administrator': return True
    if not (user in (doc.owner, doc.get('assigned_to')) or
            set(frappe.get_roles(user)).intersection({'System Manager', 'Relay Communication Manager'})):
        return False
    if not doc.messages: return False
    if (doc.get('business_doctype') or doc.get('business_name')) and not allowed(doc, user): return False
    try:
        for row in doc.messages:
            message = frappe.get_doc('Relay Message', row.message)
            if not message.has_permission('read', user=user) or not can_read_contact_as(message.relay_contact, user):
                return False
            if doc.get('business_name') and reference(message) != (doc.business_doctype, doc.business_name):
                return False
        return True
    except frappe.DoesNotExistError:
        return False


def query_condition(user=None):
    from relay_core.business_access import explicit_condition
    user = user or frappe.session.user
    if user == 'Administrator': return ''
    quoted = frappe.db.escape(user)
    gate = '1=1' if set(frappe.get_roles(user)).intersection({'System Manager', 'Relay Communication Manager'}) else (
        f'(`tabRelay Ticket`.owner={quoted} OR `tabRelay Ticket`.assigned_to={quoted})')
    messages = frappe.qb.get_query('Relay Message', fields=['name'], ignore_permissions=False,
                                   user=user, order_by='').get_sql()
    contacts = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False,
                                   user=user, order_by='').get_sql()
    links = "t.parent=`tabRelay Ticket`.name AND t.parenttype='Relay Ticket'"
    return f"""({gate}) AND ({explicit_condition('Relay Ticket', user, allow_empty=True)})
        AND EXISTS (SELECT 1 FROM `tabRelay Ticket Message` t WHERE {links})
        AND NOT EXISTS (SELECT 1 FROM `tabRelay Ticket Message` t WHERE {links}
          AND NOT EXISTS (SELECT 1 FROM `tabRelay Message` m WHERE m.name=t.message
            AND m.name IN ({messages}) AND m.relay_contact IN ({contacts})
            AND (COALESCE(`tabRelay Ticket`.business_name,'')='' OR
                 (m.business_doctype=`tabRelay Ticket`.business_doctype AND m.business_name=`tabRelay Ticket`.business_name))))"""


@frappe.whitelist(methods=['GET'])
def directory(query='', before=None, after=None, status=None, business_doctype=None, business_name=None, assigned_to=None, category=None):
    require_access()
    if not isinstance(query,str) or len(query)>80 or before and after: frappe.throw('Invalid ticket search')
    filters={}
    for key, value in dict(business_doctype=business_doctype, business_name=business_name, assigned_to=assigned_to, category=category).items():
        if value:
            if not isinstance(value, str) or len(value) > 140: frappe.throw('Invalid ticket filter')
            filters[key] = value
    if status:
        if status not in ('Open','In progress','Resolved','Closed'): frappe.throw('Invalid ticket status')
        filters['status']=status
    if before or after:
        validate_reference(before or after,'TKT');filters['name']=['<' if before else '>',before or after]
    if query:filters['subject']=['like','%'+query.replace('%','\\%').replace('_','\\_')+'%']
    rows=frappe.get_list('Relay Ticket',filters=filters,fields=['name'],order_by='name desc' if before else 'name asc',page_length=31)
    more=len(rows)>30;page=rows[:30]
    if before:page.reverse()
    items=[]
    for row in page:
        try:ticket=read(row.name)
        except frappe.PermissionError:continue
        items.append(dict(ticket,id=ticket['name']))
    return {'items':items,'previous':{'before':page[0].name} if page and (more if before else bool(after)) else None,
        'next':{'after':page[-1].name} if page and (bool(before) if before else more) else None}
