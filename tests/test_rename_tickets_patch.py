"""Ticket rename patch: order, series continuation, derived keys and stored names, empty-site safety. No site data is touched."""
import fnmatch
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from relay_core.flows.actions import _encoded, _hash
from relay_core.ticket_notifications import digest

OLD, NEW = 'RELAY-TKT-0000000002', 'TKT-00001'


class Row(dict):
    __getattr__ = dict.__getitem__


class Tables:
    """In-memory get_all/set_value over named rows, with the filter operators the patch uses."""
    def __init__(self, tables):
        self.tables = {doctype: [Row(row) for row in rows] for doctype, rows in tables.items()}

    @staticmethod
    def matches(row, filters):
        for field, condition in (filters or {}).items():
            operator, value = condition if isinstance(condition, list) else ('=', condition)
            actual = row.get(field)
            if operator == 'like' and not (isinstance(actual, str) and fnmatch.fnmatchcase(actual, value.replace('%', '*'))):
                return False
            if operator == 'in' and actual not in value or operator == '=' and actual != value:
                return False
        return True

    def get_all(self, doctype, filters=None, fields=None, pluck=None, **kwargs):
        rows = [row for row in self.tables.get(doctype, []) if self.matches(row, filters)]
        return [row[pluck] for row in rows] if pluck else [Row({f: row.get(f) for f in fields}) for row in rows]

    def set_value(self, doctype, name, field, value=None, update_modified=True):
        row = next(row for row in self.tables[doctype] if row['name'] == name)
        row.update(field if isinstance(field, dict) else {field: value})

    def row(self, doctype, name):
        return next(row for row in self.tables[doctype] if row['name'] == name)


class RenameTicketsPatchTests(unittest.TestCase):
    def setUp(self):
        self.series = iter(range(1, 100))
        self.frappe = types.SimpleNamespace(
            db=types.SimpleNamespace(table_exists=Mock(return_value=True), set_value=Mock(), commit=Mock()),
            get_all=Mock(), rename_doc=Mock(), enqueue=Mock())
        naming = types.SimpleNamespace(make_autoname=lambda key, doctype: 'TKT-%05d' % next(self.series))
        modules = {'frappe': self.frappe, 'frappe.model': types.ModuleType('frappe.model'), 'frappe.model.naming': naming}
        context = patch.dict(sys.modules, modules)
        context.start()
        self.addCleanup(context.stop)
        path = Path('relay_core/patches/v1_0/rename_tickets_to_short_names.py')
        spec = importlib.util.spec_from_file_location('tested_rename_tickets', path)
        self.patch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.patch)

    def test_no_tickets_does_nothing(self):
        self.frappe.get_all.return_value = []
        self.patch.execute()
        self.frappe.rename_doc.assert_not_called()

    def test_missing_table_does_nothing(self):
        self.frappe.db.table_exists.return_value = False
        self.patch.execute()
        self.frappe.get_all.assert_not_called()

    def use_tables(self, tables):
        self.tables = Tables(tables)
        self.frappe.get_all, self.frappe.db.set_value = self.tables.get_all, self.tables.set_value
        self.frappe.db.exists = lambda doctype, name: any(row['name'] == name for row in self.tables.tables.get(doctype, []))
        return self.tables

    def test_renames_in_creation_order_and_updates_payloads(self):
        old = ['RELAY-TKT-0000000007', 'RELAY-TKT-0000000002']
        payload = {'delivery_episodes': [['RELAY-TKT-0000000002', 1]], 'text': 'Ticket RELAY-TKT-0000000002'}
        tables = self.use_tables({'Relay Business Event Delivery': [dict(name='D1', payload=json.dumps(payload),
            payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())]})
        self.frappe.get_all = Mock(side_effect=lambda doctype, **kwargs: old if doctype == 'Relay Ticket' else tables.get_all(doctype, **kwargs))
        self.frappe.rename_doc = Mock(side_effect=lambda doctype, old_name, new_name, **kwargs: None)
        self.patch.execute()
        self.assertEqual([c.args[1:] for c in self.frappe.rename_doc.call_args_list],
                         [('RELAY-TKT-0000000007', 'TKT-00001'), ('RELAY-TKT-0000000002', 'TKT-00002')])
        self.assertTrue(all(c.kwargs == {'force': True, 'merge': False, 'rebuild_search': False} for c in self.frappe.rename_doc.call_args_list))
        self.frappe.enqueue.assert_called_once_with('frappe.utils.global_search.rebuild_for_doctype', doctype='Relay Ticket')
        delivery = tables.row('Relay Business Event Delivery', 'D1')
        saved = json.loads(delivery.payload)
        self.assertEqual(saved, {'delivery_episodes': [['TKT-00002', 1]], 'text': 'Ticket RELAY-TKT-0000000002'})
        # business_events.delivery_scope rejects a payload whose hash does not match.
        self.assertEqual(delivery.payload_hash, hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest())

    def test_subscription_key_follows_the_new_ticket_name(self):
        tables = self.use_tables({'Relay Ticket Subscription': [
            dict(name='S1', ticket=NEW, user='a@example.invalid', subscription_key=digest(OLD, 'a@example.invalid'), enabled=1)]})
        self.patch.repair_derived({OLD: NEW})
        self.assertEqual(tables.get_all('Relay Ticket Subscription', filters={'subscription_key': digest(NEW, 'a@example.invalid')},
                                        pluck='name'), ['S1'])

    def test_stale_duplicate_subscription_is_disabled(self):
        tables = self.use_tables({'Relay Ticket Subscription': [
            dict(name='S1', ticket=NEW, user='a@example.invalid', subscription_key=digest(OLD, 'a@example.invalid'), enabled=1),
            dict(name='S2', ticket=NEW, user='a@example.invalid', subscription_key=digest(NEW, 'a@example.invalid'), enabled=1)]})
        self.patch.repair_derived({OLD: NEW})
        self.assertEqual(tables.get_all('Relay Ticket Subscription', filters={'ticket': NEW, 'enabled': 1}, pluck='name'), ['S2'])

    def test_search_plan_and_action_payload_name_the_new_ticket(self):
        plan = json.dumps({'ticket': OLD, 'plan': {'reference': 'Orders'}, 'generation': 0})
        payload = json.dumps({'ticket': OLD, 'delivery_episodes': [[OLD, 2]], 'arguments': {'text': OLD + ': update'}},
                             sort_keys=True, separators=(',', ':'))
        tables = self.use_tables({'Relay Automation Run': [dict(name='R1', search_plan=plan)],
                                  'Relay Message Action': [dict(name='A1', payload=payload)]})
        self.patch.repair_derived({OLD: NEW})
        self.assertEqual(json.loads(tables.row('Relay Automation Run', 'R1').search_plan)['ticket'], NEW)
        stored = tables.row('Relay Message Action', 'A1').payload
        self.assertEqual(json.loads(stored), {'ticket': NEW, 'delivery_episodes': [[NEW, 2]], 'arguments': {'text': OLD + ': update'}})
        self.assertEqual(stored, payload.replace('"' + OLD + '"', '"' + NEW + '"'))

    def test_message_content_and_transport_arguments_keep_the_old_name(self):
        payload = {'ticket': OLD, 'delivery_episodes': [[OLD, 2]], 'tool': 'send_text',
                   'arguments': {'text': {'body': OLD}, 'reply': [OLD, 1]}, 'content': {'text': OLD}}
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        tables = self.use_tables({'Relay Message Action': [dict(name='A1', payload=encoded)]})
        self.patch.repair_derived({OLD: NEW})
        stored = json.loads(tables.row('Relay Message Action', 'A1').payload)
        self.assertEqual(stored, dict(payload, ticket=NEW, delivery_episodes=[[NEW, 2]]))

    def test_flow_action_fingerprint_and_approval_match_the_new_binding(self):
        binding = {'ticket': OLD, 'generation': 1, 'scope': {'company': 'C'}}
        fingerprint = _hash(binding)
        evidence = _encoded({'actor': 'm@example.invalid', 'scope_fingerprint': fingerprint, 'input_hash': 'i'})
        tables = self.use_tables({'Relay Flow Action': [
            dict(name='F1', scope_snapshot=_encoded(binding), scope_fingerprint=fingerprint, approval_evidence=evidence),
            dict(name='F2', scope_snapshot=_encoded(binding), scope_fingerprint='tampered', approval_evidence=None)]})
        self.patch.repair_derived({OLD: NEW})
        row = tables.row('Relay Flow Action', 'F1')
        expected = _hash(dict(binding, ticket=NEW))
        self.assertEqual((row.scope_snapshot, row.scope_fingerprint), (_encoded(dict(binding, ticket=NEW)), expected))
        self.assertEqual(json.loads(row.approval_evidence)['scope_fingerprint'], expected)
        self.assertEqual(tables.row('Relay Flow Action', 'F2').scope_fingerprint, 'tampered')

    def test_pending_notification_text_and_bell_links_use_the_new_name(self):
        body = OLD + ': Late order\nhttp://site/relay#/tickets?ticket=' + OLD
        tables = self.use_tables({
            'Relay Ticket Notification': [dict(name='N1', status='Pending', body=body), dict(name='N2', status='Submitted', body=body)],
            'Notification Log': [dict(name='L1', document_type='Relay Ticket', document_name=OLD)]})
        self.patch.repair_derived({OLD: NEW})
        self.assertEqual(tables.row('Relay Ticket Notification', 'N1').body, body.replace(OLD, NEW))
        self.assertEqual(tables.row('Relay Ticket Notification', 'N2').body, body)
        self.assertEqual(tables.row('Notification Log', 'L1').document_name, NEW)

    def test_repair_is_idempotent(self):
        plan = json.dumps({'ticket': OLD})
        tables = self.use_tables({'Relay Automation Run': [dict(name='R1', search_plan=plan)],
            'Relay Ticket Subscription': [dict(name='S1', ticket=NEW, user='a@example.invalid',
                                               subscription_key=digest(OLD, 'a@example.invalid'), enabled=1)]})
        self.patch.repair_derived({OLD: NEW})
        first = json.dumps(tables.tables, sort_keys=True)
        self.patch.repair_derived({OLD: NEW})
        self.assertEqual(json.dumps(tables.tables, sort_keys=True), first)

    def test_renamed_site_mapping_comes_from_rename_comments(self):
        self.use_tables({'Comment': [
            dict(name='C1', reference_doctype='Relay Ticket', comment_type='Edit',
                 content='renamed from <strong>RELAY-TKT-0000000002</strong> to <strong>TKT-00001</strong>'),
            dict(name='C2', reference_doctype='Relay Ticket', comment_type='Edit', content='renamed from <strong>X</strong> to <strong>Y</strong>')],
            'Relay Ticket': [dict(name=NEW)]})
        self.assertEqual(self.patch.recovered_mapping(), {OLD: NEW})
        with patch.object(self.patch, 'repair_derived') as repair:
            self.assertEqual(self.patch.repair_renamed_site(), 1)
        repair.assert_called_once_with({OLD: NEW})
        self.frappe.db.commit.assert_called_once_with()

    def test_rerun_is_a_no_op_after_rename(self):
        self.frappe.get_all.return_value = []
        self.patch.execute()
        self.patch.execute()
        self.frappe.rename_doc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
