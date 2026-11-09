"""The persona: lookup order, the AI prompt text, the save API and one persona per company."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from relay_core.ai import persona


def row(**values):
    return frappe._dict({'name': 'RELAY-PER-0000000001', 'persona_name': 'Mira', 'enabled': 1, 'company': None,
                         'instructions': '', **values})


class PersonaTests(unittest.TestCase):
    def test_the_company_persona_wins_over_the_one_for_every_company(self):
        reader = Mock(side_effect=[[row(company='Example Co')]])
        self.assertEqual(persona.find('Example Co', reader).company, 'Example Co')
        self.assertEqual(reader.call_args.kwargs['filters'], {'enabled': 1, 'company': 'Example Co'})
        reader = Mock(side_effect=[[], [row()]])
        self.assertIsNone(persona.find('Example Co', reader).company)
        self.assertEqual(reader.call_args.kwargs['filters'], {'enabled': 1, 'company': ['is', 'not set']})
        reader = Mock(return_value=[])
        self.assertIsNone(persona.find(None, reader))
        reader.assert_called_once()

    def test_prompt_gives_the_name_and_instructions_or_nothing(self):
        with patch.object(persona, 'find', return_value=row(instructions='Warm and short. Sign off as Mira.')):
            self.assertEqual(persona.prompt('Example Co'), 'Name: Mira\nWarm and short. Sign off as Mira.')
        with patch.object(persona, 'find', return_value=None):
            self.assertEqual(persona.prompt('Example Co'), '')

    def test_save_checks_write_access_and_fields(self):
        doc = Mock(name='doc')
        doc.name = 'RELAY-PER-0000000001'
        with patch.object(persona, 'require_access') as access, patch.object(frappe, 'new_doc', return_value=doc):
            with self.assertRaisesRegex(ValueError, 'Invalid persona fields'):
                persona.save({'persona_name': 'Mira', 'owner': 'x'})
            self.assertEqual(persona.save('{"persona_name": "Mira"}'), {'name': 'RELAY-PER-0000000001'})
        access.assert_called_with('Relay AI Persona', 'write')
        doc.update.assert_called_once_with({'company': '', 'persona_name': 'Mira'})
        doc.save.assert_called_once()

    def test_one_persona_per_company_and_bounded_instructions(self):
        from relay_core.relay_core.doctype.relay_ai_persona.relay_ai_persona import RelayAIPersona
        doc = SimpleNamespace(doctype='Relay AI Persona', name='RELAY-PER-0000000002', company=None, instructions='x')
        database = Mock()
        database.exists.return_value = True
        with patch.object(frappe, 'db', database), patch.object(frappe, 'throw', side_effect=frappe.DuplicateEntryError) as throw:
            with self.assertRaises(frappe.DuplicateEntryError):
                RelayAIPersona.validate(doc)
            self.assertIn('every company', throw.call_args.args[0])
            self.assertEqual(database.exists.call_args.args[1],
                             {'company': ['is', 'not set'], 'name': ['!=', 'RELAY-PER-0000000002']})
            database.exists.return_value = False
            doc.instructions = 'x' * (persona.MAX_INSTRUCTIONS + 1)
            with self.assertRaises(frappe.DuplicateEntryError):
                RelayAIPersona.validate(doc)
            self.assertIn('4000', throw.call_args.args[0])
            doc.instructions = 'Warm.'
            RelayAIPersona.validate(doc)


if __name__ == '__main__':
    unittest.main()
