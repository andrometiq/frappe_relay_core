"""Local relay.test acceptance of playbooks after a migrate with worktree code; no model or channel calls.

The class adds fake Relay AI Knowledge rows and runs the move patch on them. Run from the app folder:
SITES_PATH=<bench>/sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_ai_playbooks_site.py'
The moved rows and the fake legacy rows are deleted afterwards; the shipped app playbook stays.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SITES = os.environ['SITES_PATH']
sys.path.insert(0, str(ROOT))
import frappe

from relay_core.ai import knowledge, playbooks
from relay_core.ai.registry import ToolContext
from relay_core.patches.v1_0 import move_ai_knowledge_to_playbooks as move

APP_PLAYBOOK = 'relay_core/handoff-etiquette'
CUSTOMER = ('Customer', 'Kestrel Traders')
LEGACY_ROWS = (('Acme tone', 1, None, None, 'Greet Acme Textiles customers by first name and keep replies short.'),
               ('Acme pricing', 1, 'Acme Textiles', 'Customer', 'Never quote a price; Sampleville staff confirm prices.'),
               ('Old rule', 0, None, 'Supplier', 'Ask suppliers for the bill number.'))


class PlaybookSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import relay_core
        assert Path(relay_core.__file__).resolve().parents[1] == ROOT
        frappe.init(site='relay.test', sites_path=SITES)
        frappe.connect()
        assert frappe.local.site == 'relay.test'
        frappe.set_user('Administrator')
        cls.ai_on = patch('relay_core.ai_features.is_enabled', return_value=True)
        cls.ai_on.start()
        assert not frappe.get_all(move.LEGACY, filters={'migrated_to': ['is', 'not set']}, limit_page_length=1)
        for title, enabled, company, doctype, text in LEGACY_ROWS:
            doc = frappe.get_doc({'doctype': move.LEGACY, 'title': title, 'enabled': enabled, 'company': company,
                                  'business_doctype': doctype, 'instructions': text})
            doc.flags.ignore_validate = True
            doc.insert()
        move.execute()
        frappe.db.commit()
        cls.legacy = frappe.get_all(move.LEGACY, fields=move.FIELDS, order_by='name asc', limit_page_length=0)

    @classmethod
    def tearDownClass(cls):
        frappe.db.rollback()
        for row in cls.legacy:
            frappe.db.delete(playbooks.DOCTYPE, f'desk/{row.name}')
            frappe.db.delete(move.LEGACY, row.name)
        frappe.db.delete(playbooks.DOCTYPE, {'title': 'Integration tone'})
        frappe.db.commit()
        cls.ai_on.stop()
        frappe.destroy()

    def tearDown(self):
        frappe.db.rollback()

    def test_1_every_legacy_row_moved_with_the_same_prompt(self):
        for row in self.legacy:
            moved = frappe.get_doc(playbooks.DOCTYPE, f'desk/{row.name}')
            self.assertEqual(row.migrated_to, moved.name)
            self.assertEqual((moved.title, moved.instructions, moved.enabled, moved.company, moved.business_doctype),
                             (row.title, row.instructions, row.enabled, row.company, row.business_doctype))
            self.assertEqual((moved.is_global, moved.is_system_generated, moved.audience), (1, 0, 'customer'))
        for business, company in move.scopes(self.legacy):
            self.assertEqual(knowledge.prompt(business, company), move.legacy_text(self.legacy, business, company))

    def test_2_a_second_patch_run_changes_nothing(self):
        before = frappe.get_all(playbooks.DOCTYPE, fields=['name', 'modified'], order_by='name asc')
        move.execute()
        self.assertEqual(frappe.get_all(playbooks.DOCTYPE, fields=['name', 'modified'], order_by='name asc'), before)

    def test_3_legacy_rows_are_read_only(self):
        doc = frappe.get_doc(move.LEGACY, self.legacy[0].name)
        doc.title = 'Changed'
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_4_the_app_file_is_a_locked_customer_playbook(self):
        doc = frappe.get_doc(playbooks.DOCTYPE, APP_PLAYBOOK)
        self.assertEqual((doc.app, doc.is_system_generated, doc.audience, doc.is_global), ('relay_core', 1, 'customer', 0))
        doc.enabled = 0
        doc.save()
        doc.instructions = 'Changed by hand.'
        with self.assertRaisesRegex(frappe.ValidationError, 'SKILL.md'):
            doc.save()
        with self.assertRaisesRegex(frappe.ValidationError, 'SKILL.md'):
            frappe.delete_doc(playbooks.DOCTYPE, APP_PLAYBOOK)
        with self.assertRaisesRegex(frappe.ValidationError, 'desk/'):
            frappe.get_doc({'doctype': playbooks.DOCTYPE, 'playbook_key': 'acme_app/fake', 'title': 'Fake',
                            'is_global': 1, 'instructions': 'Text'}).insert()

    def test_5_sync_deletes_a_gone_app_row_and_its_skill_links_but_never_desk_rows(self):
        frappe.flags.in_playbook_sync = True
        try:
            frappe.get_doc({'doctype': playbooks.DOCTYPE, 'playbook_key': 'relay_core/gone-file', 'title': 'gone-file',
                            'app': 'relay_core', 'is_system_generated': 1, 'description': 'Gone.',
                            'instructions': 'Gone.'}).insert()
        finally:
            frappe.flags.in_playbook_sync = False
        frappe.get_doc({'doctype': 'Relay AI Skill Playbook', 'playbook': 'relay_core/gone-file', 'parent': 'FAKE-SKILL',
                        'parenttype': 'Relay AI Skill', 'parentfield': 'playbooks'}).db_insert()
        self.assertEqual(playbooks.sync(), [APP_PLAYBOOK])
        self.assertFalse(frappe.db.exists(playbooks.DOCTYPE, 'relay_core/gone-file'))
        self.assertFalse(frappe.db.exists('Relay AI Skill Playbook', {'playbook': 'relay_core/gone-file'}))
        for row in self.legacy:
            self.assertTrue(frappe.db.exists(playbooks.DOCTYPE, f'desk/{row.name}'))

    def test_6_a_bound_playbook_loads_only_for_its_skill(self):
        skill = frappe._dict(business_doctype='Customer', playbooks=[frappe._dict(playbook=APP_PLAYBOOK)])
        ctx = ToolContext(run=None, skill=skill, user='Administrator', business=CUSTOMER, scope={'company': 'Acme Textiles'})
        text = playbooks.load_playbook({'name': APP_PLAYBOOK}, ctx)
        self.assertIn('team member will reply', text)
        self.assertEqual(playbooks.copy_texts(skill, CUSTOMER, 'Acme Textiles'), (text,))
        self.assertTrue(playbooks.index(skill, CUSTOMER, 'Acme Textiles').startswith(APP_PLAYBOOK + ': How to tell'))
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            playbooks.load_playbook({'name': f'desk/{self.legacy[0].name}'}, ctx)

    def test_7_the_knowledge_api_writes_global_desk_playbooks(self):
        name = knowledge.save({'title': 'Integration tone', 'enabled': 1, 'instructions': 'Keep it short.'})['name']
        self.assertTrue(name.startswith('desk/RELAY-KB-'))
        listed = [row.name for row in knowledge.directory()['items']]
        self.assertIn(name, listed)
        self.assertNotIn(APP_PLAYBOOK, listed)
        with self.assertRaisesRegex(ValueError, 'Relay AI Playbook'):
            knowledge.save({'title': 'Changed'}, name=APP_PLAYBOOK)
