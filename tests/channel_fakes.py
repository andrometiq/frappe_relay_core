"""A small in-memory Frappe stand-in for Relay Channel, endpoint and message rows in unit tests."""
import itertools
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from frappe import _dict


def matches(row, filters):
    for field, wanted in (filters or {}).items():
        value = row.get(field)
        if isinstance(wanted, (list, tuple)):
            operator, operand = wanted
            if operator == 'is':
                if bool(value) != (operand == 'set'):
                    return False
            elif operator == '!=' and value == operand:
                return False
            elif operator == 'in' and value not in operand:
                return False
            elif operator == 'not in' and value in operand:
                return False
        elif value != wanted:
            return False
    return True


class FakeDoc(_dict):
    def __init__(self, store, values):
        super().__init__(values)
        self._store = store
        self.flags = _dict()

    def update(self, values=None, **more):
        dict.update(self, values or {}, **more)
        return self

    def insert(self, ignore_permissions=False):
        self._store.insert(self)
        return self

    def save(self, ignore_permissions=False):
        if self.get('name'):
            self._store.write(self)
        else:
            self._store.insert(self)
        return self

    def check_permission(self, permission='read'):
        return True


class FakeSite:
    """Tables by DocType; get_all/get_value/exists/set_value read and write them in creation order."""

    def __init__(self, on_insert=None, **tables):
        self.on_insert = on_insert or {}
        self.counter = itertools.count(1)
        self.tables = {}
        for doctype, rows in tables.items():
            for row in rows:
                self.add(doctype.replace('_', ' '), row)
        self.queued = []
        self.frappe = self.module()

    def add(self, doctype, row):
        row = _dict(row)
        row.setdefault('name', f'{doctype}-{next(self.counter)}')
        row.setdefault('creation', next(self.counter))
        self.tables.setdefault(doctype, []).append(row)
        return row

    def rows(self, doctype, filters=None):
        return [row for row in self.tables.get(doctype, []) if matches(row, filters)]

    def insert(self, doc):
        values = {key: value for key, value in doc.items() if not key.startswith('_') and key != 'flags'}
        doctype = values.pop('doctype')
        self.on_insert.get(doctype, lambda row: None)(values)
        doc.update(self.add(doctype, values))

    def write(self, doc):
        row = next(row for rows in self.tables.values() for row in rows if row.name == doc.name)
        row.update({key: value for key, value in doc.items() if not key.startswith('_') and key not in ('flags', 'doctype')})

    def get_all(self, doctype, filters=None, fields=None, pluck=None, order_by=None, limit_page_length=0, **_):
        rows = self.rows(doctype, filters)
        if order_by:
            for part in reversed(order_by.split(',')):
                field, *direction = part.split()
                rows = sorted(rows, key=lambda row: (row.get(field) is None, row.get(field) or 0),
                              reverse=bool(direction) and direction[0] == 'desc')
        if limit_page_length:
            rows = rows[:limit_page_length]
        if pluck:
            return [row[pluck] for row in rows]
        return [_dict({field: row.get(field) for field in (fields or ['name'])}) for row in rows]

    def get_value(self, doctype, filters, fieldname='name', as_dict=False, order_by=None, **_):
        filters = {'name': filters} if isinstance(filters, str) else filters
        rows = self.get_all(doctype, filters, fields=fieldname if isinstance(fieldname, list) else [fieldname],
                            order_by=order_by)
        if not rows:
            return None
        if as_dict:
            return rows[0]
        return tuple(rows[0].values()) if isinstance(fieldname, list) else rows[0][fieldname]

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            return FakeDoc(self, doctype)
        return FakeDoc(self, dict(self.rows(doctype, {'name': name})[0], doctype=doctype))

    def set_value(self, doctype, name, field, value=None, **_):
        changes = field if isinstance(field, dict) else {field: value}
        self.rows(doctype, {'name': name})[0].update(changes)

    def module(self):
        db = SimpleNamespace(get_value=self.get_value, exists=lambda doctype, filters: bool(
            self.rows(doctype, {'name': filters} if isinstance(filters, str) else filters)),
            set_value=self.set_value, commit=Mock(), count=lambda doctype, filters=None: len(self.rows(doctype, filters)))
        return SimpleNamespace(db=db, flags=SimpleNamespace(), get_all=self.get_all, get_list=self.get_all, get_doc=self.get_doc,
                               cache=SimpleNamespace(lock=lambda *a, **k: nullcontext()),
                               enqueue=lambda *a, **k: self.queued.append((a, k)), throw=throw,
                               PermissionError=PermissionError, ValidationError=ValueError, DuplicateEntryError=DuplicateEntryError,
                               session=_dict(user='Administrator'), whitelist=lambda **k: (lambda f: f))


class DuplicateEntryError(ValueError):
    pass


def throw(message, exception=ValueError):
    raise exception(message)
