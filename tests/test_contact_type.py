import json
import unittest
from pathlib import Path


DOCTYPE_ROOT = Path("relay_core/relay_core/doctype")


class ContactTypeTests(unittest.TestCase):
    def test_contact_type_uses_business_doctype_as_its_name(self):
        metadata = json.loads(
            (DOCTYPE_ROOT / "relay_contact_type/relay_contact_type.json").read_text()
        )

        self.assertEqual(metadata["name"], "Relay Contact Type")
        self.assertEqual(metadata["autoname"], "field:business_doctype")
        self.assertEqual(metadata["naming_rule"], "By fieldname")

    def test_standard_contact_is_implicit_and_grouping_is_a_picker(self):
        metadata = json.loads(
            (DOCTYPE_ROOT / "relay_contact_type/relay_contact_type.json").read_text()
        )
        fields = {field["fieldname"]: field for field in metadata["fields"]}

        self.assertNotIn("contact_doctype", fields)
        self.assertEqual(fields["grouping_field"]["fieldtype"], "Autocomplete")
        self.assertTrue(fields["business_doctype"]["set_only_once"])

    def test_one_to_one_configuration_uses_linked_entity_names(self):
        cases = {
            "relay_automation_policy": "channel",
            "relay_email_rule": "channel",
            "relay_email_preference": "user",
        }

        for folder, linked_field in cases.items():
            with self.subTest(folder=folder):
                metadata = json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())
                fields = {field["fieldname"]: field for field in metadata["fields"]}
                self.assertEqual(metadata["autoname"], f"field:{linked_field}")
                self.assertTrue(fields[linked_field]["set_only_once"])
