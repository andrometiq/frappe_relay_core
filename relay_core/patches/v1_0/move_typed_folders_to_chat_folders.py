import frappe


def execute():
    """Turn each user's typed folder names into Relay Chat Folder records and link the conversations to them."""
    frappe.reload_doc('relay_core', 'doctype', 'relay_chat_folder')
    frappe.reload_doc('relay_core', 'doctype', 'relay_conversation_state')
    state = frappe.qb.DocType('Relay Conversation State')
    typed = (frappe.qb.from_(state).select(state.user, state.folder).distinct()
             .where(state.folder.isnotnull() & (state.folder != '')).orderby(state.user).orderby(state.folder).run())
    existing = set(frappe.get_all('Relay Chat Folder', pluck='name'))
    created = {}
    for user, typed_name in typed:
        if typed_name in existing:
            continue
        label = typed_name.strip()[:50] or 'Folder'
        # The unique index ignores case, so names that differ only in case share one folder.
        key = (user, label.lower())
        if key not in created:
            folder = frappe.get_doc({'doctype': 'Relay Chat Folder', 'user': user, 'folder_name': label, 'owner': user,
                                     'sort_order': sum(1 for other, _ in created if other == user) + 1})
            folder.set_new_name()
            folder.db_insert()
            created[key] = folder.name
        frappe.qb.update(state).set(state.folder, created[key]).where((state.user == user) & (state.folder == typed_name)).run()
