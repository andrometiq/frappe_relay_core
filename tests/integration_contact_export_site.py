"""Contact export on the local site: same rows as the per-contact export, list filters, scope and a query bound.

Run from the worktree with RELAY_TEST_SITE=relay.test, SITES_PATH and RELAY_AUTOMATION_TEST_SITES set to the bench sites folder.
All fixture rows are bulk inserted in one transaction and rolled back at the end.
"""
import time
from io import BytesIO
from unittest.mock import patch

import frappe
from channel_site_fixtures import init
from openpyxl import load_workbook
from relay_core import contact_import, contacts

init()
COUNT = 2000
META = ['creation', 'modified', 'owner', 'modified_by', 'docstatus']
stamp = 'SIM-EXPORT-' + frappe.generate_hash(length=6).upper()


def old_rows():
    """The export before keyset pages: one Contact document and one access check per contact and link."""
    from relay_core.business_access import people_query
    yield list(contact_import.COLUMNS)
    start = 0
    while True:
        names = people_query(fields=['name'], order_by='name', offset=start, limit=200).run(pluck=True)
        if not names:
            break
        for name in names:
            person = contact_import.existing_person(name)
            base = [person.get('mobile_no') or person.get('phone') or '', person.get('email_id') or '',
                    person.get('full_name') or person.get('first_name') or name]
            links = person.get('links') or []
            for link in links:
                if contacts.readable(link):
                    yield [*base, link.link_doctype, link.link_name]
            if not links:
                yield [*base, '', '']
        start += len(names)


def measured(rows):
    calls = [0]
    sql = frappe.db.sql

    def counted(*args, **kwargs):
        calls[0] += 1
        return sql(*args, **kwargs)
    with patch.object(frappe.db, 'sql', counted):
        began = time.perf_counter()
        result = list(rows)
        return result, calls[0], time.perf_counter() - began


def fixtures():
    """Every fifth contact: no links, one record, a record and a missing one, Customer and Supplier, Supplier only."""
    now, user = frappe.utils.now(), frappe.session.user
    meta = [now, now, user, user, 0]
    people, customers, links = [], [], []
    for index in range(COUNT):
        name, record, supplier = f'{stamp}-{index:05d}', f'{stamp}-C{index:05d}', f'{stamp}-S{index:05d}'
        people.append([name, f'Sim {index}', f'Sim export {index}', f'+9190000{index:05d}' if index % 2 else '',
                       f'sim-{index}@example.invalid', *meta])
        kind = index % 5
        if kind in (1, 2, 3):
            customers.append([record, record, *meta])
        wanted = ([], [('Customer', record)], [('Customer', record), ('Customer', record + '-MISSING')],
                  [('Customer', record), ('Supplier', supplier)], [('Supplier', supplier)])[kind]
        links += [[frappe.generate_hash(length=12), name, 'Contact', 'links', idx + 1, *link, *meta]
                  for idx, link in enumerate(wanted)]
    frappe.db.bulk_insert('Contact', ['name', 'first_name', 'full_name', 'mobile_no', 'email_id', *META], people)
    frappe.db.bulk_insert('Customer', ['name', 'customer_name', *META], customers)
    frappe.db.bulk_insert('Dynamic Link', ['name', 'parent', 'parenttype', 'parentfield', 'idx', 'link_doctype', 'link_name', *META], links)


def rejected(**filters):
    try:
        list(contact_import.export_rows(**filters))
    except (frappe.PermissionError, frappe.DoesNotExistError):
        return True
    return False


try:
    assert contact_import.allowed() and frappe.get_all('Relay Contact Type', {'enabled': 1}, pluck='business_doctype') == ['Customer']
    fixtures()
    old, old_queries, old_seconds = measured(old_rows())
    new, new_queries, new_seconds = measured(contact_import.export_rows())
    # The old export listed contacts by name descending; the new one follows the Contacts list, ascending.
    assert new[0] == old[0] and sorted(new[1:]) == sorted(old[1:]), 'Batched export rows differ from the per-contact export'
    mine = [row for row in new if row[2].startswith('Sim export ')]
    assert [row[1] for row in mine] == sorted((row[1] for row in mine), key=lambda mail: int(mail[4:-16])), 'Rows follow contact names'
    assert len(mine) == COUNT // 5 * 4, len(mine)
    assert not any(row[3] == 'Supplier' or row[4].endswith('-MISSING') for row in new)
    hidden = {f'Sim export {index}' for index in range(4, COUNT, 5)}
    assert not hidden & {row[2] for row in new}, 'Supplier-only contacts are outside the Relay scope'
    pages = frappe.db.count('Contact') // contact_import.EXPORT_PAGE + 1
    assert new_queries <= 10 + 3 * pages, new_queries

    customer = [row for row in new[1:] if row[3] == 'Customer']
    assert list(contact_import.export_rows(business_type='Customer'))[1:] == customer
    assert list(contact_import.export_rows(unlinked=1))[1:] == [row for row in new[1:] if row[3] == '']
    record = f'{stamp}-C00002'
    assert list(contact_import.export_rows(business_type='Customer', business_name=record))[1:] == [row for row in customer if row[4] == record]
    assert list(contact_import.export_rows(query='Sim export 1999', unlinked=1))[1:] == []
    assert list(contact_import.export_rows(query='Sim export 1995', unlinked=1))[1:] == [['+919000001995', 'sim-1995@example.invalid', 'Sim export 1995', '', '']]
    assert rejected(business_type='Supplier') and rejected(business_type='Customer', business_name=f'{stamp}-C00004')

    frappe.local.response = frappe._dict()
    contact_import.export(business_type='Customer')
    assert frappe.local.response.filename == 'Relay contacts - Customer.xlsx'
    sheet = load_workbook(BytesIO(frappe.local.response.filecontent), read_only=True).active
    assert [[cell or '' for cell in row] for row in sheet.iter_rows(values_only=True)][1:] == customer

    frappe.set_user('Guest')
    try:
        contact_import.export()
        raise AssertionError('Guest exported contacts')
    except frappe.PermissionError:
        pass
    frappe.set_user('Administrator')
    print(f'{len(new) - 1} rows. Before: {old_queries} queries, {old_seconds:.2f} s. After: {new_queries} queries, {new_seconds:.2f} s.')
finally:
    frappe.set_user('Administrator')
    frappe.db.rollback()
    assert not frappe.db.exists('Contact', {'name': ['like', stamp + '%']})
    frappe.destroy()
