"""Ticket statuses, categories and types that managers configure. A status always counts as one fixed state."""
import frappe

STATES = ('Open', 'In progress', 'Resolved', 'Closed')
DOCTYPES = {'status': 'Relay Ticket Status', 'category': 'Relay Ticket Category', 'type': 'Relay Ticket Type'}
TICKET_FIELDS = {'status': 'ticket_status', 'category': 'category', 'type': 'ticket_type'}
DEFAULT_STATUSES = (('Open', 'Open', 'amber', 10), ('In progress', 'In progress', 'blue', 20),
                    ('Resolved', 'Resolved', 'green', 30), ('Closed', 'Closed', 'gray', 40))
DEFAULT_CATEGORIES = (('Support', 'blue', 10),)
DEFAULT_TYPES = (('General', 'gray', 10),)
LEGACY_CATEGORIES = (('Query', 'gray', 20), ('Payment evidence', 'amber', 30), ('Other', 'gray', 40))


def _kind(kind):
    if kind not in DOCTYPES:
        frappe.throw('Invalid ticket setting')
    return DOCTYPES[kind]


def _seed(doctype, rows):
    """Fill an empty list only, so a later migrate keeps the values a manager renamed, removed or reordered."""
    if frappe.db.count(doctype):
        return
    for values in rows:
        frappe.get_doc({'doctype': doctype, 'enabled': 1, **values}).insert(ignore_permissions=True)


def seed_defaults(extra_categories=()):
    """Create the default values on a site that has none of that kind yet."""
    _seed(DOCTYPES['status'], [dict(label=label, state=state, colour=colour, sort_order=order, is_default=1)
                               for label, state, colour, order in DEFAULT_STATUSES])
    _seed(DOCTYPES['category'], [dict(label=label, colour=colour, sort_order=order)
                                 for label, colour, order in (*DEFAULT_CATEGORIES, *extra_categories)])
    _seed(DOCTYPES['type'], [dict(label=label, colour=colour, sort_order=order) for label, colour, order in DEFAULT_TYPES])


def default_status(state):
    """The enabled status a plain state change uses: the default one, else the first by sort order."""
    rows = frappe.get_all(DOCTYPES['status'], filters={'state': state, 'enabled': 1}, fields=['name'],
                          order_by='is_default desc, sort_order asc, name asc', limit_page_length=1)
    return rows[0].name if rows else None


def preferred(kind, label):
    """`label` when it is enabled, else the first enabled value, for tickets that the system opens itself."""
    doctype = _kind(kind)
    if label and frappe.db.get_value(doctype, label, 'enabled'):
        return label
    rows = frappe.get_all(doctype, filters={'enabled': 1}, fields=['name'], order_by='sort_order asc, name asc', limit_page_length=1)
    return rows[0].name if rows else label


def require_enabled(kind, label):
    enabled = frappe.db.get_value(DOCTYPES[kind], label, 'enabled')
    if enabled is None:
        frappe.throw(f'Invalid ticket {kind}')
    if not enabled:
        frappe.throw(f'The ticket {kind} "{label}" is turned off in Ticket settings')


def apply(doc):
    """Check category and type, and keep the state (`status`) and the configured `ticket_status` in step."""
    previous = doc.get_doc_before_save()
    for kind in ('category', 'type'):
        value = doc.get(TICKET_FIELDS[kind])
        if value and (not previous or value != previous.get(TICKET_FIELDS[kind])):
            require_enabled(kind, value)
    chosen = doc.get('ticket_status')
    if chosen:
        state = frappe.db.get_value(DOCTYPES['status'], chosen, 'state')
        if not state:
            frappe.throw('Invalid ticket status')
        if not previous or chosen != previous.get('ticket_status'):
            require_enabled('status', chosen)
            doc.status = state
            return
        if state == doc.status:
            return
    if doc.status not in STATES:
        frappe.throw('Invalid ticket status')
    doc.ticket_status = default_status(doc.status)


def _rows(kind, manager):
    doctype = DOCTYPES[kind]
    fields = ['name', 'label', 'colour', 'enabled', 'sort_order'] + (['state', 'is_default'] if kind == 'status' else [])
    rows = frappe.get_all(doctype, fields=fields, order_by='sort_order asc, name asc', limit_page_length=0)
    if manager:
        field = TICKET_FIELDS[kind]
        used = {row[field]: row.tickets for row in frappe.get_all('Relay Ticket', filters={field: ['is', 'set']},
                fields=[field, {'COUNT': 'name', 'as': 'tickets'}], group_by=field)}
    for row in rows:
        row['enabled'] = int(row['enabled'])
        if manager:
            row['tickets'] = int(used.get(row['name'], 0))
    return rows


@frappe.whitelist(methods=['GET'])
def read():
    """All three lists in one call: every Relay user reads them; the counts and edit rights are for managers."""
    from relay_core.permissions import require_access
    require_access('Relay Ticket', 'read')
    manager = bool(frappe.has_permission(DOCTYPES['status'], 'write'))
    return {'can_manage': manager, 'states': list(STATES),
            **{plural: _rows(kind, manager) for kind, plural in (('status', 'statuses'), ('category', 'categories'), ('type', 'types'))}}


def _require_manager(kind):
    if not frappe.has_permission(_kind(kind), 'write'):
        frappe.throw('Not permitted', frappe.PermissionError)


@frappe.whitelist(methods=['POST'])
def save(kind, label, name=None, colour=None, enabled=None, state=None, is_default=None):
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
    for key, value in (('colour', colour), ('state', state), ('enabled', enabled), ('is_default', is_default)):
        if value is not None and key in doc.meta.get_valid_columns():
            doc.set(key, int(value) if key in ('enabled', 'is_default') else value)
    doc.save()
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


def validate_setting(doc):
    """Keep at least one enabled value, and at least one enabled status for each state. Used statuses keep their state."""
    previous = doc.get_doc_before_save()
    if previous and doc.doctype == DOCTYPES['status'] and doc.state != previous.state:
        used = frappe.db.count('Relay Ticket', {'ticket_status': doc.name})
        if used:
            frappe.throw(f'{used} tickets use this status. Create a new status instead.')
    if not previous or not previous.enabled:
        return
    kind = next(key for key, value in DOCTYPES.items() if value == doc.doctype)
    scope = {'state': previous.state} if kind == 'status' else {}
    leaving = not doc.enabled or kind == 'status' and doc.state != previous.state
    others = frappe.db.count(doc.doctype, {'enabled': 1, 'name': ['!=', doc.name], **scope})
    if leaving and not others:
        frappe.throw(f'Keep at least one enabled {"status for " + previous.state if scope else kind}')


def after_setting_saved(doc):
    """One default per state: a new default turns the others of that state off."""
    if doc.doctype == DOCTYPES['status'] and doc.is_default:
        for name in frappe.get_all(doc.doctype, filters={'state': doc.state, 'is_default': 1, 'name': ['!=', doc.name]}, pluck='name'):
            frappe.db.set_value(doc.doctype, name, 'is_default', 0)


def block_used_setting(doc):
    """A value that tickets use is turned off, never deleted."""
    kind = next(key for key, value in DOCTYPES.items() if value == doc.doctype)
    if frappe.db.exists('Relay Ticket', {TICKET_FIELDS[kind]: doc.name}):
        frappe.throw(f'Tickets use "{doc.name}". Turn it off instead of deleting it.')
