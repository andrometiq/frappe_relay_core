"""Relay Memory key patch: company and provider from the last folded message's channel, unresolved rows listed,
old unique key dropped. No site data is touched."""
import contextlib
import importlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from frappe import _dict

PATCH = 'relay_core.patches.v1_0.add_memory_company_and_provider'


class MemoryKeyPatchTests(unittest.TestCase):
    def run_patch(self, memories, messages, db_type='mariadb', has_index=True):
        tables = {
            'Relay Channel': [_dict(name='CH-1', company='Sim Company', channel='WhatsApp'),
                              _dict(name='CH-2', company='Other Company', channel='Telegram')],
            'Relay Memory': memories, 'Relay Message': messages}

        def get_all(doctype, filters=None, fields=None, as_list=False, **kwargs):
            rows = tables[doctype]
            if doctype == 'Relay Memory':
                rows = [row for row in rows if not row.get('provider')]
            if doctype == 'Relay Message':
                rows = [row for row in rows if row.name in filters['name'][1]]
            return [tuple(row[field] for field in fields) if as_list else row for row in rows]

        updates = []
        db = types.SimpleNamespace(set_value=lambda *args, **kwargs: updates.append(args), sql_ddl=Mock(),
                                   has_index=Mock(return_value=has_index))
        fake = types.SimpleNamespace(get_all=get_all, db=db, conf=_dict(db_type=db_type))
        output = io.StringIO()
        with patch.dict(sys.modules, frappe=fake), contextlib.redirect_stdout(output):
            sys.modules.pop(PATCH, None)
            importlib.import_module(PATCH).execute()
        sys.modules.pop(PATCH, None)
        return updates, output.getvalue(), db.sql_ddl

    def test_rows_take_company_and_provider_from_the_last_message_channel(self):
        memories = [_dict(name='MEM-1', last_message='MSG-1'), _dict(name='MEM-2', last_message='MSG-2'),
                    _dict(name='MEM-3', last_message='MSG-GONE'), _dict(name='MEM-4', last_message=''),
                    _dict(name='MEM-5', last_message='MSG-3'),
                    _dict(name='MEM-6', last_message='MSG-1', provider='Email')]
        messages = [_dict(name='MSG-1', channel='CH-1'), _dict(name='MSG-2', channel='CH-2'),
                    _dict(name='MSG-3', channel='CH-DELETED')]
        updates, output, ddl = self.run_patch(memories, messages)
        self.assertEqual(updates, [('Relay Memory', 'MEM-1', {'company': 'Sim Company', 'provider': 'WhatsApp'}),
                                   ('Relay Memory', 'MEM-2', {'company': 'Other Company', 'provider': 'Telegram'})])
        self.assertIn('MEM-3, MEM-4, MEM-5', output)
        self.assertNotIn('MEM-6', output, 'Rows that have a provider are left alone')
        ddl.assert_called_once_with('ALTER TABLE `tabRelay Memory` DROP INDEX relay_memory_period')

    def test_an_empty_table_or_a_site_without_the_old_key_is_safe(self):
        updates, output, ddl = self.run_patch([], [], has_index=False)
        self.assertEqual((updates, output), ([], ''))
        ddl.assert_not_called()
        _, _, ddl = self.run_patch([], [], db_type='postgres')
        self.assertIn('DROP CONSTRAINT IF EXISTS relay_memory_period', ddl.call_args.args[0])

    def test_patch_runs_after_the_model_sync(self):
        patches = Path('relay_core/patches.txt').read_text()
        self.assertIn(PATCH, patches.split('[post_model_sync]')[1].split())
