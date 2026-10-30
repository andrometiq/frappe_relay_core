"""Personal chat folders: each user names their own folders and files conversations into them."""
import frappe
from relay_core.business_access import document_name
from frappe.query_builder.functions import Count, Max
from relay_core import features
from relay_core.permissions import require_access

FOLDER = 'Relay Chat Folder'
STATE = 'Relay Conversation State'


def clean_folder_name(value):
    name = value.strip() if isinstance(value, str) else ''
    if not name or len(name) > 50 or any(ord(c) < 32 for c in name):
        frappe.throw('Folder names must contain 1 to 50 printable characters')
    return name


def validate_folder(doc):
    require_access()
    if doc.user != frappe.session.user or doc.owner != frappe.session.user:
        frappe.throw('Folders belong to their user', frappe.PermissionError)
    doc.folder_name = clean_folder_name(doc.folder_name)
    if frappe.db.exists(FOLDER, {'user': doc.user, 'folder_name': doc.folder_name, 'name': ['!=', doc.name]}):
        frappe.throw(f'You already have a folder named {doc.folder_name}')


def own_folder(folder):
    """The current user's folder document; another user's folder is reported as missing."""
    document_name(folder)
    if frappe.db.get_value(FOLDER, folder, 'user') != frappe.session.user:
        frappe.throw('Folder not found', frappe.DoesNotExistError)
    return frappe.get_doc(FOLDER, folder)


def permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    return user == 'Administrator' or doc.user == user


def query(user=None):
    user = user or frappe.session.user
    return '' if user == 'Administrator' else f'`tabRelay Chat Folder`.user={frappe.db.escape(user)}'


@frappe.whitelist(methods=['GET'])
def folders():
    """My folders in display order, each with the number of conversations filed in it."""
    require_access()
    features.require('folders')
    state = frappe.qb.DocType(STATE)
    counts = dict(frappe.qb.from_(state).select(state.folder, Count('*'))
                  .where((state.user == frappe.session.user) & state.folder.isnotnull() & (state.folder != ''))
                  .groupby(state.folder).run())
    rows = frappe.get_all(FOLDER, filters={'user': frappe.session.user}, fields=['name', 'folder_name', 'sort_order'],
                          order_by='sort_order asc, folder_name asc', limit_page_length=0)
    return [dict(row, count=counts.get(row.name, 0)) for row in rows]


@frappe.whitelist(methods=['POST'])
def create(folder_name):
    require_access()
    features.require('folders')
    table = frappe.qb.DocType(FOLDER)
    last = frappe.qb.from_(table).select(Max(table.sort_order)).where(table.user == frappe.session.user).run()[0][0] or 0
    doc = frappe.get_doc({'doctype': FOLDER, 'user': frappe.session.user, 'folder_name': folder_name, 'sort_order': last + 1})
    doc.insert()
    return {'name': doc.name, 'folder_name': doc.folder_name, 'sort_order': doc.sort_order, 'count': 0}


@frappe.whitelist(methods=['POST'])
def rename(folder, folder_name):
    require_access()
    features.require('folders')
    doc = own_folder(folder)
    doc.folder_name = folder_name
    doc.save()
    return {'name': doc.name, 'folder_name': doc.folder_name}


@frappe.whitelist(methods=['POST'])
def delete(folder):
    """Remove the folder; its conversations stay in the inbox without a folder."""
    require_access()
    features.require('folders')
    doc = own_folder(folder)
    state = frappe.qb.DocType(STATE)
    frappe.qb.update(state).set(state.folder, None).where((state.user == frappe.session.user) & (state.folder == doc.name)).run()
    doc.delete()
    return {'name': doc.name}
