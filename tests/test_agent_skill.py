"""The external agent skill: valid frontmatter, only real tools, and no internals or real credentials."""
import re
import unittest
from pathlib import Path

import yaml

import relay_core.mcp_tools  # noqa: F401  Registers every tool.
from relay_core.mcp_tools import registry

FOLDER = Path('integrations/agent-skill/relay')
INTERNALS = re.compile(r'doctype|relay_core|python|redis|mariadb|openai|anthropic|frappe_tools|\bmodel\b|\.py\b', re.IGNORECASE)


class AgentSkillTests(unittest.TestCase):
    def test_frontmatter_names_the_skill_and_when_to_use_it(self):
        text = (FOLDER / 'SKILL.md').read_text()
        meta = yaml.safe_load(re.match(r'\A---\n(.*?)\n---\n', text, re.DOTALL).group(1))
        self.assertEqual(meta['name'], 'relay')
        self.assertTrue(meta['description'].startswith('Use when'))

    def test_every_tool_it_names_exists(self):
        text = (FOLDER / 'SKILL.md').read_text()
        named = set(re.findall(r'`([a-z]+(?:_[a-z]+)+)`', text)) - {'request_key', 'after_message', 'reply_window'}
        self.assertTrue({'reply_context', 'persona_read', 'chat_send_text', 'chat_send_template'} <= named)
        self.assertEqual(named - {entry.name for entry in registry.listed()}, set())

    def test_no_internals_or_real_credentials(self):
        self.assertIsNone(INTERNALS.search((FOLDER / 'SKILL.md').read_text()))
        credentials = (FOLDER / 'credentials.example.md').read_text()
        self.assertIn('Authorization: token <api_key>:<api_secret>', credentials)
        self.assertIsNone(re.search(r'token [0-9a-f]{10,}', credentials))


if __name__ == '__main__':
    unittest.main()
