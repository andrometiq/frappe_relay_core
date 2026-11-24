from collections import defaultdict

import frappe
from frappe.model.document import Document

# identity.contacts_by_phone compares stored phones without these characters.
SEPARATORS = str.maketrans('', '', ' -().')


class RelayPhoneIndex(Document):
    pass


def on_doctype_update():
    frappe.db.add_index('Relay Phone Index', ['reversed_digits'], 'relay_phone_reversed_digits')


def reversed_digits(phone: str) -> str:
    return phone.translate(SEPARATORS)[::-1][:140]


def contacts(tail: str) -> list[str]:
    """Contacts with a stored phone that ends in tail, read as an index prefix."""
    return frappe.get_all('Relay Phone Index', filters={'reversed_digits': ['like', reversed_digits(tail) + '%']},
                          pluck='contact', distinct=True)


def sync(person, method=None):
    """Contact on_update: the Contact's rows follow its current phones."""
    phones = [row.phone for row in person.get('phone_nos') or []] + [person.get('mobile_no'), person.get('phone')]
    frappe.db.delete('Relay Phone Index', {'contact': person.name})
    insert({person.name: phones})


def remove(person, method=None):
    frappe.db.delete('Relay Phone Index', {'contact': person.name})


def rename(person, method=None, old=None, new=None, merge=False):
    """Contact after_rename: rows keep pointing at the Contact; a merge's phones join the kept Contact."""
    frappe.db.set_value('Relay Phone Index', {'contact': old}, 'contact', new, update_modified=False)


def rebuild():
    """Index the phones of every Contact."""
    phones = defaultdict(list)
    for name, mobile, phone in frappe.db.sql('SELECT name, mobile_no, phone FROM `tabContact`'):
        phones[name] += [mobile, phone]
    for parent, phone in frappe.db.sql("SELECT parent, phone FROM `tabContact Phone` WHERE parenttype = 'Contact'"):
        phones[parent].append(phone)
    frappe.db.delete('Relay Phone Index')
    insert(phones)


def insert(phones: dict[str, list]):
    frappe.db.bulk_insert('Relay Phone Index', ['name', 'contact', 'reversed_digits'], [
        (frappe.generate_hash(length=20), contact, digits)
        for contact, values in phones.items()
        for digits in {reversed_digits(value) for value in values if value} - {''}])
