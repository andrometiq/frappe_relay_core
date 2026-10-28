"""Ticket statuses and types that managers configure. Each status is of type Open or Closed."""
import frappe

STATUS_TYPES = ('Open', 'Closed')
DOCTYPES = {'status': 'Relay Ticket Status', 'type': 'Relay Ticket Type'}
TICKET_FIELDS = {'status': 'ticket_status', 'type': 'ticket_type'}
DEFAULT_STATUSES = (('Open', 'blue', 10), ('Closed', 'gray', 20))


def _kind(kind):
    if kind not in DOCTYPES:
        frappe.throw('Invalid ticket setting')
    return DOCTYPES[kind]


def seed_defaults():
    """Create the Open and Closed statuses when the site has no status of that type yet."""
    doctype = DOCTYPES['status']
    for label, colour, order in DEFAULT_STATUSES:
        if not frappe.db.exists(doctype, {'state': label}) and not frappe.db.exists(doctype, label):
            frappe.get_doc({'doctype': doctype, 'label': label, 'state': label, 'colour': colour,
                            'sort_order': order}).insert(ignore_permissions=True)


def status_of(status_type):
    """The first status of that type: new tickets start in the Open one, Close moves to the Closed one."""
    rows = frappe.get_all(DOCTYPES['status'], filters={'state': status_type}, pluck='name',
                          order_by='sort_order asc, name asc', limit_page_length=1)
    if not rows:
        frappe.throw(f'Add a ticket status of type {status_type} in Ticket settings')
    return rows[0]


def is_closed(doc):
    return frappe.db.get_value(DOCTYPES['status'], doc.get('ticket_status'), 'state') == 'Closed'


def apply(doc):
    """A ticket without a status starts in the first Open status."""
    if not doc.get('ticket_status'):
        doc.ticket_status = status_of('Open')


def _rows(kind, manager):
    doctype = DOCTYPES[kind]
    fields = ['name', 'label', 'colour', 'sort_order'] + (['state'] if kind == 'status' else [])
    rows = frappe.get_all(doctype, fields=fields, order_by='sort_order asc, name asc', limit_page_length=0)
    if manager:
        field = TICKET_FIELDS[kind]
        used = {row[field]: row.tickets for row in frappe.get_all('Relay Ticket', filters={field: ['is', 'set']},
                fields=[field, {'COUNT': 'name', 'as': 'tickets'}], group_by=field)}
        for row in rows:
            row['tickets'] = int(used.get(row['name'], 0))
    return rows


@frappe.whitelist(methods=['GET'])
def read():
    """Statuses and types in one call: every Relay user reads them; the counts and edit rights are for managers."""
    from relay_core.permissions import require_access
    require_access('Relay Ticket', 'read')
    manager = bool(frappe.has_permission(DOCTYPES['status'], 'write'))
    return {'can_manage': manager, 'status_types': list(STATUS_TYPES),
            'statuses': _rows('status', manager), 'types': _rows('type', manager)}


def _require_manager(kind):
    if not frappe.has_permission(_kind(kind), 'write'):
        frappe.throw('Not permitted', frappe.PermissionError)


@frappe.whitelist(methods=['POST'])
def save(kind, label, name=None, colour=None, state=None):
    """Add a value, or change one: a new `label` renames it everywhere it is used."""
    _require_manager(kind)
    doctype = _kind(kind)
    label = (label or '').strip() if isinstance(label, str) else ''
    if not label or len(label) > 60:
        frappe.throw('Name must contain 1–60 characters')
    if name:
        if name != label:
            frappe.rename_doc(doctype, name, label)
        doc = frappe.get_doc(doctype, label)
    else:
        doc = frappe.new_doc(doctype)
        doc.label = label
        doc.sort_order = (frappe.db.sql(f'select coalesce(max(sort_order), 0) from `tab{doctype}`')[0][0] or 0) + 10
    if colour is not None:
        doc.colour = colour
    if state is not None and kind == 'status':
        doc.state = state
    doc.save()
    return read()


@frappe.whitelist(methods=['POST'])
def remove(kind, name):
    """Delete a value that no ticket uses."""
    _require_manager(kind)
    frappe.delete_doc(_kind(kind), name)
    return read()


@frappe.whitelist(methods=['POST'])
def reorder(kind, names):
    """Set the sort order of a list from the order of `names`."""
    _require_manager(kind)
    doctype = _kind(kind)
    names = frappe.parse_json(names) if isinstance(names, str) else names
    if not isinstance(names, list) or sorted(names) != sorted(frappe.get_all(doctype, pluck='name')):
        frappe.throw('Send every value once')
    for index, name in enumerate(names):
        if frappe.db.get_value(doctype, name, 'sort_order') != (index + 1) * 10:
            doc = frappe.get_doc(doctype, name)
            doc.sort_order = (index + 1) * 10
            doc.save()
    return read()


def _keep_one_of_type(status_type, name):
    if not frappe.db.count(DOCTYPES['status'], {'state': status_type, 'name': ['!=', name]}):
        frappe.throw(f'Keep at least one status of type {status_type}')


def validate_status(doc):
    """A status that tickets use keeps its type, and each type keeps at least one status."""
    previous = doc.get_doc_before_save()
    if not previous or doc.state == previous.state:
        return
    used = frappe.db.count('Relay Ticket', {'ticket_status': doc.name})
    if used:
        frappe.throw(f'{used} tickets use this status. Create a new status instead.')
    _keep_one_of_type(previous.state, doc.name)


def block_used_setting(doc):
    """A value that tickets use is never deleted."""
    kind = next(key for key, value in DOCTYPES.items() if value == doc.doctype)
    if frappe.db.exists('Relay Ticket', {TICKET_FIELDS[kind]: doc.name}):
        frappe.throw(f'Tickets use "{doc.name}", so it cannot be deleted.')
    if kind == 'status':
        _keep_one_of_type(doc.state, doc.name)
