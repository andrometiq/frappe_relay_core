"""Playbooks: SKILL.md parsing and sync, global prompt text, bound index and loading, copy checks and the move patch."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import test_ai_skills as fixtures
from test_ai_skills import Doc
from relay_core.ai import knowledge, playbooks, reply_guard
from relay_core.ai.registry import ToolContext
from relay_core.ai.registry.builtin import CoreTools
from relay_core.patches.v1_0 import move_ai_knowledge_to_playbooks as move
from relay_core.relay_core.doctype.relay_ai_playbook import relay_ai_playbook as controller

ETIQUETTE = '''---
name: handoff-etiquette
description: How to tell the customer that staff will take over.
relay: customer
---
Say that a team member will reply in this chat and never promise a time.
'''
SECRET = 'Offer the Sampleville loyalty rebate only after the customer has placed three orders in one month.'


def playbook(name, **values):
    return Doc(dict(name=name, title=name, description='', instructions='Text', company=None,
                    business_doctype=None), **values)


class FrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, text, folder='handoff-etiquette'):
        path = self.root / folder / 'SKILL.md'
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_a_relay_file_gives_its_playbook(self):
        self.assertEqual(playbooks.read(self.write(ETIQUETTE)), dict(title='handoff-etiquette',
            description='How to tell the customer that staff will take over.', audience='customer',
            instructions='Say that a team member will reply in this chat and never promise a time.'))

    def test_a_file_without_a_relay_key_is_ignored(self):
        for text in (ETIQUETTE.replace('relay: customer\n', ''), 'No frontmatter at all.'):
            with self.subTest(text=text[:20]):
                self.assertIsNone(playbooks.read(self.write(text)))

    def test_invalid_frontmatter_is_refused(self):
        for text in (ETIQUETTE.replace('relay: customer', 'relay: everyone'),
                     ETIQUETTE.replace('name: handoff-etiquette', 'name: Handoff_Etiquette'),
                     ETIQUETTE.replace('description: How', 'description: ' + 'x' * 1025 + ' How'),
                     ETIQUETTE.replace('description: How to tell the customer that staff will take over.', 'description: ""'),
                     ETIQUETTE.replace('relay: customer', 'relay: [customer'),
                     ETIQUETTE.split('---\n', 2)[0] + '---\n' + ETIQUETTE.split('---\n', 2)[1] + '---\n'):
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                playbooks.read(self.write(text))
        with self.assertRaisesRegex(ValueError, 'folder name'):
            playbooks.read(self.write(ETIQUETTE, folder='other-name'))

    def test_skill_files_skips_hidden_and_reports_a_cut_off_scan(self):
        self.write(ETIQUETTE)
        self.write(ETIQUETTE, folder='.hidden')
        (self.root / 'notes').mkdir()
        self.assertEqual(playbooks.skill_files(self.root), ([self.root / 'handoff-etiquette' / 'SKILL.md'], False))
        self.assertEqual(playbooks.skill_files(self.root / 'missing'), ([], False))
        with patch.object(playbooks, 'MAX_FOLDER_ENTRIES', 2):
            self.assertEqual(playbooks.skill_files(self.root), ([], True))


class SyncTests(unittest.TestCase):
    """sync() against a fake framework: one app with a skills folder and existing rows."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.f = fixtures.framework()
        self.f.ValidationError = type('ValidationError', (Exception,), {})
        self.f.get_installed_apps = Mock(return_value=['acme_app'])
        self.f.get_app_source_path = Mock(side_effect=lambda app, folder: str(self.root / folder))
        self.f.delete_doc = Mock()
        self.f.db.get_value.return_value = None
        self.existing = []
        self.f.get_all.side_effect = lambda doctype, filters, pluck: list(self.existing)
        self.flags = []
        self.save = Mock(side_effect=lambda **kw: self.flags.append(self.f.flags.in_playbook_sync))
        save = self.save

        class Saved(Doc):
            def save(self, **kw): return save(**kw)
        self.doc = Saved()
        self.f.get_doc.return_value = self.doc
        self.enterContext(patch.object(playbooks, 'frappe', self.f))

    def write(self, folder, text):
        (self.root / 'skills' / folder).mkdir(parents=True, exist_ok=True)
        (self.root / 'skills' / folder / 'SKILL.md').write_text(text, encoding='utf-8')

    def test_a_new_file_creates_a_locked_row_during_sync_only(self):
        self.write('handoff-etiquette', ETIQUETTE)
        self.assertEqual(playbooks.sync(), ['acme_app/handoff-etiquette'])
        self.f.get_doc.assert_called_once_with({'doctype': playbooks.DOCTYPE, 'playbook_key': 'acme_app/handoff-etiquette'})
        self.assertEqual((self.doc.app, self.doc.audience, self.doc.is_system_generated), ('acme_app', 'customer', 1))
        self.assertEqual(self.flags, [True])
        self.assertFalse(self.f.flags.in_playbook_sync)

    def test_an_unchanged_row_is_not_saved_and_a_changed_row_is(self):
        self.write('handoff-etiquette', ETIQUETTE)
        stored = dict(playbooks.read(self.root / 'skills' / 'handoff-etiquette' / 'SKILL.md'),
                      app='acme_app', is_system_generated=1)
        self.f.db.get_value.return_value = Doc(stored)
        playbooks.sync()
        self.save.assert_not_called()
        self.f.db.get_value.return_value = Doc(stored, instructions='Old text')
        playbooks.sync()
        self.f.get_doc.assert_called_once_with(playbooks.DOCTYPE, 'acme_app/handoff-etiquette')
        self.save.assert_called_once()

    def test_rows_gone_from_disk_or_without_relay_key_are_unlinked_and_deleted(self):
        self.write('handoff-etiquette', ETIQUETTE)
        self.write('flow-only', ETIQUETTE.replace('handoff-etiquette', 'flow-only').replace('relay: customer\n', ''))
        self.existing = ['acme_app/handoff-etiquette', 'acme_app/flow-only', 'acme_app/removed']
        playbooks.sync()
        self.assertEqual(self.f.db.delete.call_args_list, [call('Relay AI Skill Playbook', {'playbook': 'acme_app/flow-only'}),
            call('Relay AI Skill Playbook', {'playbook': 'acme_app/removed'})])
        self.assertEqual([c.args[1] for c in self.f.delete_doc.call_args_list], ['acme_app/flow-only', 'acme_app/removed'])
        deleted_filter = self.f.get_all.call_args.kwargs['filters']
        self.assertEqual(deleted_filter, {'is_system_generated': 1, 'app': ['is', 'set']})

    def test_an_invalid_file_is_logged_and_keeps_its_row(self):
        self.write('handoff-etiquette', ETIQUETTE.replace('relay: customer', 'relay: everyone'))
        self.existing = ['acme_app/handoff-etiquette']
        self.assertEqual(playbooks.sync(), [])
        self.f.log_error.assert_called_once()
        self.f.delete_doc.assert_not_called()

    def test_a_row_the_controller_refuses_is_logged_and_skipped(self):
        self.write('handoff-etiquette', ETIQUETTE)
        self.save.side_effect = self.f.ValidationError
        self.assertEqual(playbooks.sync(), [])
        self.f.log_error.assert_called_once()

    def test_a_cut_off_scan_keeps_every_row_of_the_app(self):
        self.write('handoff-etiquette', ETIQUETTE)
        self.existing = ['acme_app/handoff-etiquette', 'acme_app/old']
        with patch.object(playbooks, 'MAX_FOLDER_ENTRIES', 0):
            self.assertEqual(playbooks.sync(), [])
        self.f.delete_doc.assert_not_called()
        self.f.log_error.assert_called_once()


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.framework()
        self.enterContext(patch.object(playbooks, 'frappe', self.f))
        self.skill = Doc(playbooks=[Doc(playbook='desk/returns'), Doc(playbook='desk/rebates')], business_doctype='Customer')
        self.business = ('Customer', 'Kestrel Traders')

    def test_global_text_keeps_matching_customer_rows_in_name_order(self):
        self.f.get_all.return_value = [playbook('desk/a', title='All', instructions='Be brief.'),
            playbook('desk/b', title='Acme', instructions='Quote in INR.', company='Acme Textiles'),
            playbook('desk/c', title='Suppliers', instructions='Ask for the bill.', business_doctype='Supplier')]
        self.assertEqual(playbooks.global_text(self.business, 'Acme Textiles'), 'All\nBe brief.\n\nAcme\nQuote in INR.')
        self.assertEqual(playbooks.global_text(self.business, 'Northwind Hosiery'), 'All\nBe brief.')
        self.assertEqual(self.f.get_all.call_args.kwargs['filters'], {'enabled': 1, 'is_global': 1, 'audience': 'customer'})

    def test_global_text_refuses_more_than_the_caps(self):
        self.f.get_all.return_value = [playbook(f'desk/{n}') for n in range(101)]
        with self.assertRaisesRegex(ValueError, 'Too many'):
            playbooks.global_text(self.business, None)
        self.f.get_all.return_value = [playbook(f'desk/{n}', instructions='x' * 2000) for n in range(4)]
        with self.assertRaisesRegex(ValueError, '8000'):
            playbooks.global_text(self.business, None)

    def test_index_and_load_offer_only_bound_enabled_customer_playbooks(self):
        self.f.get_all.return_value = [playbook('desk/rebates', description='When a customer\nasks about rebates.',
                                                instructions=SECRET),
                                       playbook('desk/returns', instructions='Other company text.', company='Northwind Hosiery')]
        self.assertEqual(playbooks.index(self.skill, self.business, 'Acme Textiles'),
                         'desk/rebates: When a customer asks about rebates.')
        self.assertEqual(self.f.get_all.call_args.kwargs['filters'], {'name': ['in', ['desk/returns', 'desk/rebates']],
            'enabled': 1, 'is_global': 0, 'audience': 'customer'})
        ctx = ToolContext(run=None, skill=self.skill, user='agent@example.com', business=self.business,
                          scope={'company': 'Acme Textiles'})
        self.assertEqual(playbooks.load_playbook({'name': 'desk/rebates'}, ctx), SECRET)
        for name in ('desk/returns', 'acme_app/unbound'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '^Playbook is unavailable$'):
                playbooks.load_playbook({'name': name}, ctx)

    def test_a_skill_without_playbooks_reads_nothing(self):
        self.assertEqual(playbooks.copy_texts(Doc(), self.business, None), ())
        self.f.get_all.assert_not_called()


class CopyCheckTests(unittest.TestCase):
    """Bound playbook text joins the verbatim-copy check in the run and again at delivery."""

    def setUp(self):
        self.enterContext(patch('relay_core.ai.knowledge.prompt', return_value=''))
        self.enterContext(patch('relay_core.ai.playbooks.copy_texts', return_value=(SECRET,)))
        self.enterContext(patch('relay_core.ai.registry.builtin.copy_texts', return_value=(SECRET,)))
        self.f = fixtures.framework()
        self.f.get_all.return_value = []
        self.f.db.get_value.return_value = 'Acme Textiles'
        self.enterContext(patch.object(reply_guard, 'frappe', self.f))
        self.enterContext(patch('relay_core.business_access.candidates', return_value=[('Customer', 'Kestrel Traders')]))

    def test_core_tools_start_with_bound_playbook_text(self):
        skill = Doc(playbooks=[Doc(playbook='desk/rebates')])
        core = CoreTools(skill, ('Customer', 'Kestrel Traders'), {'company': 'Acme Textiles'}, Mock(), [], Mock(), None)
        self.assertEqual(core.knowledge, [SECRET])

    def test_delivery_blocks_a_copied_playbook(self):
        run = Doc(decision=json.dumps({}))
        message = Doc(channel='CHANNEL-1', sender_endpoint='919999999999', relay_contact='SELF',
                      business_doctype='Customer', business_name='Kestrel Traders', content='Any rebate?')
        skill = Doc(instructions='Answer briefly.')
        reply_guard.check_delivery(run, skill, message, 'A team member will reply about rebates.')
        with self.assertRaises(reply_guard.ReplyBlocked):
            reply_guard.check_delivery(run, skill, message, SECRET)


class KnowledgeFacadeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.framework()
        self.f.parse_json = json.loads
        self.f.new_doc = Mock(return_value=Doc())
        self.enterContext(patch.object(knowledge, 'frappe', self.f))
        self.enterContext(patch.object(knowledge, 'require_access'))
        self.enterContext(patch('relay_core.ai_features.is_enabled', return_value=True))
        self.enterContext(patch.object(knowledge, 'make_autoname', return_value='RELAY-KB-0000000007'))

    def test_prompt_is_the_global_playbook_text(self):
        with patch.object(playbooks, 'global_text', return_value='Be brief.') as text:
            self.assertEqual(knowledge.prompt(('Customer', 'Kestrel Traders'), 'Acme Textiles'), 'Be brief.')
        text.assert_called_once_with(('Customer', 'Kestrel Traders'), 'Acme Textiles')

    def test_save_creates_a_global_desk_playbook_and_lists_only_those(self):
        values = dict(title='Tone', enabled=1, instructions='Be brief.')
        doc = self.f.new_doc.return_value
        self.assertEqual(knowledge.save(json.dumps(values)), {'name': None})
        self.assertEqual(doc, dict(values, playbook_key='desk/RELAY-KB-0000000007', **knowledge.STANDING))
        self.f.get_list.return_value = []
        knowledge.directory(after='desk/RELAY-KB-0000000001')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'],
                         dict(knowledge.STANDING, name=['>', 'desk/RELAY-KB-0000000001']))

    def test_save_refuses_app_and_bound_playbooks_and_unknown_fields(self):
        for row in (Doc(knowledge.STANDING, is_system_generated=1), Doc(knowledge.STANDING, is_global=0)):
            self.f.get_doc.return_value = row
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'Relay AI Playbook'):
                knowledge.save({'title': 'Tone'}, name='acme_app/handoff-etiquette')
        with self.assertRaisesRegex(ValueError, 'Invalid knowledge fields'):
            knowledge.save({'is_global': 0}, name='desk/RELAY-KB-0000000001')


class MovePatchTests(unittest.TestCase):
    def setUp(self):
        self.rows = [Doc(name='RELAY-KB-0000000001', title='Tone', enabled=1, company=None, business_doctype=None,
                         instructions='Be brief.', migrated_to=None),
                     Doc(name='RELAY-KB-0000000002', title='Acme', enabled=0, company='Acme Textiles',
                         business_doctype='Customer', instructions='Quote in INR.', migrated_to=None)]
        self.f = fixtures.framework()
        self.f.get_all.return_value = self.rows
        self.f.db.exists.return_value = False
        self.f.db.count.return_value = 2
        self.enterContext(patch.object(move, 'frappe', self.f))

    def test_each_row_becomes_a_global_desk_playbook_with_the_same_prompts(self):
        with patch.object(move, 'global_text', side_effect=lambda business, company: move.legacy_text(self.rows, business, company)):
            move.execute()
        created = [c.args[0] for c in self.f.get_doc.call_args_list]
        self.assertEqual([row['playbook_key'] for row in created], ['desk/RELAY-KB-0000000001', 'desk/RELAY-KB-0000000002'])
        self.assertEqual(created[1], {'doctype': 'Relay AI Playbook', 'playbook_key': 'desk/RELAY-KB-0000000002',
            'title': 'Acme', 'enabled': 0, 'company': 'Acme Textiles', 'business_doctype': 'Customer',
            'instructions': 'Quote in INR.', 'is_global': 1, 'audience': 'customer', 'is_system_generated': 0})
        self.f.db.set_value.assert_any_call('Relay AI Knowledge', 'RELAY-KB-0000000002', 'migrated_to',
                                            'desk/RELAY-KB-0000000002', update_modified=False)

    def test_a_changed_prompt_or_missing_row_fails_the_patch(self):
        with patch.object(move, 'global_text', return_value='Different'), self.assertRaisesRegex(AssertionError, 'differs'):
            move.execute()
        self.f.db.count.return_value = 1
        with self.assertRaisesRegex(AssertionError, 'Moved 1 of 2'):
            move.execute()

    def test_a_second_run_changes_nothing(self):
        for row in self.rows:
            row.migrated_to = 'desk/' + row.name
        move.execute()
        self.f.get_doc.assert_not_called()
        self.f.db.set_value.assert_not_called()

    def test_scopes_cover_each_company_and_business_type(self):
        self.assertEqual(move.scopes(self.rows), {(('Customer', ''), 'Acme Textiles'), (('Customer', ''), ''),
                                                  (('', ''), 'Acme Textiles'), (('', ''), '')})


class GlobalCapTests(unittest.TestCase):
    def validate(self, **flags):
        doc = controller.RelayAIPlaybook.__new__(controller.RelayAIPlaybook)
        doc.__dict__.update(doctype=playbooks.DOCTYPE, name='desk/RELAY-KB-0000000101', playbook_key='desk/RELAY-KB-0000000101',
                            is_system_generated=0, enabled=1, is_global=1, description='', instructions='Be brief.')
        with patch.multiple(controller.frappe, db=Mock(count=Mock(return_value=100)), flags=Doc(flags),
                            throw=Mock(side_effect=ValueError)):
            doc.validate()

    def test_a_desk_save_over_the_global_cap_is_refused(self):
        with self.assertRaises(ValueError):
            self.validate()

    def test_the_knowledge_move_copies_rows_over_the_global_cap(self):
        self.validate(in_patch=True)
