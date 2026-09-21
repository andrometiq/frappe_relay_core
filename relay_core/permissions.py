"""Server-side Relay authorization. Never trust role names supplied by a client."""
MANAGER = 'Relay Communication Manager'
USER = 'Relay Communication User'


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
    for name in (MANAGER, USER):
        if not frappe.db.exists('Role', name):
            frappe.get_doc({'doctype': 'Role', 'role_name': name, 'desk_access': 1}).insert()


def sequential_name(kind):
    """Frappe series uses a transaction-locked counter, not a random hash."""
    from frappe.model.naming import make_autoname
    prefixes = {'message': 'RELAY-MSG-', 'contact': 'RELAY-CON-', 'channel': 'RELAY-CH-'}
    return make_autoname(prefixes[kind] + '.##########')


def after_migrate():
    import frappe
    install_roles()
    frappe.db.add_index('Relay Message', ['relay_contact', 'name'], 'relay_contact_history')
    frappe.db.add_index('Relay Message', ['relay_contact', 'channel', 'name'], 'relay_channel_history')
