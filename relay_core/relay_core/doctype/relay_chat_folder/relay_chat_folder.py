import frappe
from frappe.model.document import Document


class RelayChatFolder(Document):
    def validate(self):
        from relay_core.chat_folders import validate_folder
        validate_folder(self)


def on_doctype_update():
    frappe.db.add_unique('Relay Chat Folder', ['user', 'folder_name'], 'relay_user_folder_name')
