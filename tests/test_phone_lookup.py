"""contacts_by_phone(number) reads candidates from the Relay Phone Index and keeps the full-scan matches and order.
SQLite stands in for MariaDB; the queries are the production ones."""
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

from frappe import _dict

from relay_core import identity
from relay_core.relay_core.doctype.relay_phone_index import relay_phone_index as phone_index

NUMBER = '919876543210'
SCHEMA = """
CREATE TABLE `tabContact` (name TEXT, creation TEXT, mobile_no TEXT, phone TEXT);
CREATE TABLE `tabContact Phone` (parent TEXT, parenttype TEXT, phone TEXT);
CREATE TABLE `tabRelay Contact` (name TEXT, contact TEXT);
CREATE TABLE `tabDynamic Link` (parent TEXT, parenttype TEXT, link_doctype TEXT);
CREATE TABLE `tabRelay Phone Index` (name TEXT, contact TEXT, reversed_digits TEXT);
"""


class Database:
    """The frappe.db calls the phone lookup makes, run on SQLite."""

    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.queries = []

    def sql(self, query, values=None, as_dict=False):
        self.queries.append((query, values))
        params = {}
        for key, value in (values or {}).items():
            if isinstance(value, (list, tuple)):
                names = [f'{key}{index}' for index in range(len(value))]
                query = query.replace(f'%({key})s', '(' + ', '.join(':' + name for name in names) + ')')
                params.update(zip(names, value))
            else:
                query = query.replace(f'%({key})s', ':' + key)
                params[key] = value
        rows = self.connection.execute(query, params).fetchall()
        return [_dict(row) for row in rows] if as_dict else [tuple(row) for row in rows]

    def delete(self, doctype, filters=None):
        where = ' AND '.join(f'{field} = :{field}' for field in filters or {})
        self.connection.execute(f'DELETE FROM `tab{doctype}`' + (' WHERE ' + where if where else ''), filters or {})

    def bulk_insert(self, doctype, fields, values):
        self.connection.executemany(f'INSERT INTO `tab{doctype}` ({", ".join(fields)}) VALUES ({", ".join("?" * len(fields))})',
                                    [tuple(map(str, row)) for row in values])


class Frappe:
    def __init__(self, db):
        self.db = db

    def get_all(self, doctype, filters, pluck, distinct):
        (field, (operator, value)), = filters.items()
        self.db.queries.append((doctype, filters))
        rows = self.db.connection.execute(f'SELECT DISTINCT {pluck} FROM `tab{doctype}` WHERE {field} LIKE ?', (value,))
        return [row[0] for row in rows]

    def generate_hash(self, length):
        return uuid4().hex[:length]


class PhoneLookupTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.enterContext(patch.object(phone_index, 'frappe', Frappe(self.db)))
        self.enterContext(patch('frappe.db', self.db, create=True))

    def person(self, name, creation, phones=(), mobile_no=None, phone=None, relay=None, customer=False):
        self.db.connection.execute('INSERT INTO `tabContact` VALUES (?, ?, ?, ?)', (name, creation, mobile_no, phone))
        for value in phones:
            self.db.connection.execute("INSERT INTO `tabContact Phone` VALUES (?, 'Contact', ?)", (name, value))
        if relay:
            self.db.connection.execute('INSERT INTO `tabRelay Contact` VALUES (?, ?)', (relay, name))
        if customer:
            self.db.connection.execute("INSERT INTO `tabDynamic Link` VALUES (?, 'Contact', 'Customer')", (name,))
        phone_index.sync(_dict(name=name, phone_nos=[_dict(phone=value) for value in phones],
                               mobile_no=mobile_no, phone=phone))

    def lookup(self, number=None):
        return identity.contacts_by_phone(number, region='IN')

    def test_formatted_numbers_match_as_the_full_scan_does(self):
        self.person('Child row', '2026-01-01', phones=['+91 98765-43210'])
        self.person('Mobile', '2026-01-02', mobile_no='098765 43210')
        self.person('Phone', '2026-01-03', phone='9876543210')
        self.person('Dotted', '2026-01-04', phones=['(+91) 98765.43210'])
        self.person('Same tail abroad', '2026-01-05', phones=['+1 (987) 654-3210'])
        self.person('Other', '2026-01-06', mobile_no='+91 91234 56789')

        found = self.lookup(NUMBER)
        self.assertEqual(found[NUMBER], ['Child row', 'Mobile', 'Phone', 'Dotted'])
        self.assertEqual(found[NUMBER], self.lookup()[NUMBER])
        self.assertNotIn('Other', sum(found.values(), []))

    def test_relay_contacts_come_first_then_customers_then_oldest(self):
        self.person('Oldest', '2026-01-01', mobile_no='+91 98765 43210')
        self.person('Newer', '2026-02-01', phones=['98765 43210'])
        self.person('Customer', '2026-03-01', phone='098765-43210', customer=True)
        self.person('Chat', '2026-04-01', phones=['919876543210'], relay='RELAY-CON-1')
        self.assertEqual(self.lookup(NUMBER)[NUMBER], ['Chat', 'Customer', 'Oldest', 'Newer'])

    def test_lookup_reads_only_index_candidates(self):
        self.person('Match', '2026-01-01', phones=['+91 98765 43210'])
        for index in range(50):
            self.person(f'Unrelated {index}', '2026-01-02', mobile_no=f'+91 90000 {index:05d}')
        self.db.queries.clear()

        self.assertEqual(self.lookup(NUMBER), {NUMBER: ['Match']})
        (doctype, filters), (query, values) = self.db.queries
        self.assertEqual(filters, {'reversed_digits': ['like', '0123456789%']}, 'An index prefix, not a leading wildcard')
        self.assertIn('c.name IN %(names)s', query)
        self.assertEqual(values['names'], ['Match'])

    def test_number_without_candidates_skips_the_contact_query(self):
        self.person('Other', '2026-01-01', mobile_no='+91 91234 56789')
        self.db.queries.clear()
        self.assertEqual(self.lookup(NUMBER), {})
        self.assertEqual([entry[0] for entry in self.db.queries], ['Relay Phone Index'])

    def test_contact_save_replaces_its_rows_and_delete_removes_them(self):
        self.person('Ravi', '2026-01-01', phones=['+91 98765 43210', '+91-98765-43210'], mobile_no='')
        self.assertEqual(self.index_rows(), [('Ravi', '012345678919+')])
        phone_index.sync(_dict(name='Ravi', phone_nos=[], mobile_no='91234 56789', phone=None))
        self.assertEqual(self.index_rows(), [('Ravi', '9876543219')])
        phone_index.remove(_dict(name='Ravi'))
        self.assertEqual(self.index_rows(), [])

    def test_rebuild_indexes_every_contact_phone(self):
        self.db.connection.execute("INSERT INTO `tabContact` VALUES ('Ravi', '2026-01-01', '98765 43210', NULL)")
        self.db.connection.execute("INSERT INTO `tabContact Phone` VALUES ('Ravi', 'Contact', '+91 91234-56789')")
        self.db.connection.execute("INSERT INTO `tabContact Phone` VALUES ('Lead', 'Lead', '+91 90000 00000')")
        self.db.connection.execute("INSERT INTO `tabRelay Phone Index` VALUES ('stale', 'Gone', '1')")
        phone_index.rebuild()
        self.assertEqual(self.index_rows(), [('Ravi', '0123456789'), ('Ravi', '987654321919+')])

    def index_rows(self):
        return sorted(tuple(row) for row in self.db.connection.execute(
            'SELECT contact, reversed_digits FROM `tabRelay Phone Index`'))


class HookTests(unittest.TestCase):
    def test_contact_saves_and_deletes_keep_the_phone_index(self):
        from relay_core import hooks
        events = hooks.doc_events['Contact']
        self.assertEqual(events['on_update'], ['relay_core.contact_lifecycle.on_update',
                                               'relay_core.relay_core.doctype.relay_phone_index.relay_phone_index.sync'])
        self.assertEqual(events['after_delete'], 'relay_core.relay_core.doctype.relay_phone_index.relay_phone_index.remove')


if __name__ == '__main__':
    unittest.main()
