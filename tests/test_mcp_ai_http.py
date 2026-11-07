"""MCP AI setup tools on a real site: the AI switch, roles, and records that the AI screens show."""
import base64
import json
import secrets
import unittest
from unittest.mock import patch

from test_mcp_http import MCPSite

AUDIENCE = ['Customer']


class MCPAISetupTests(MCPSite):
    @classmethod
    def add_users(cls, frappe):
        from channel_site_fixtures import user
        cls.operator = user('relay-mcp-ai-manager@example.invalid', manager=True)
        cls.staff = user('relay-mcp-ai-staff@example.invalid')
        cls.outsider = cls.plain_user(frappe, 'relay-mcp-ai-outsider@example.invalid')
        for actor in (cls.operator, cls.staff, cls.outsider):
            cls.add_token(frappe, actor)
        cls.ai_was = frappe.db.get_single_value('Relay Settings', 'enable_ai_features')
        cls.created = []

    @classmethod
    def tearDownClass(cls):
        import frappe
        cls.set_ai(1)
        for doctype, name in reversed(cls.created):
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
        cls.set_ai(cls.ai_was)
        super().tearDownClass()

    @classmethod
    def set_ai(cls, value):
        import frappe
        frappe.set_user('Administrator')
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', value)
        frappe.db.commit()

    def setUp(self):
        import frappe
        self.set_ai(1)
        frappe.enqueue.reset_mock()
        self.stamp = secrets.token_hex(4)

    def save(self, tool, values, **arguments):
        """A create over MCP; the record is removed after the class."""
        result = self.tool(tool, {'values': values, 'request_key': 'key-' + secrets.token_hex(8), **arguments})
        self.assertFalse(result['isError'], result)
        doctype = {'events_save': 'Relay AI Event', 'knowledge_save': 'Relay AI Playbook', 'skills_save': 'Relay AI Skill'}[tool]
        self.created.append((doctype, result['structuredContent']['name']))
        return result['structuredContent']['name']

    def as_manager(self, function, *args):
        """A screen API call as the manager, in a fresh snapshot that sees the server's commits."""
        import frappe
        frappe.db.commit()
        frappe.set_user(self.operator)
        try:
            return function(*args)
        finally:
            frappe.set_user('Administrator')

    def error(self, tool, arguments, actor=None):
        result = self.tool(tool, arguments, actor)
        self.assertTrue(result['isError'], result)
        return result['content'][0]['text']

    def test_switch_off_refuses_every_ai_tool_with_the_hint(self):
        from relay_core.mcp_tools.ai import AI_OFF
        self.set_ai(0)
        for tool, arguments in (('events_list', {}), ('skills_options', {'kind': 'business_doctype'}),
                                ('knowledge_save', {'values': {'title': 'Off', 'instructions': 'x'}, 'request_key': 'off-key-001'})):
            self.assertEqual(self.error(tool, arguments), AI_OFF)

    def test_roles_match_the_ai_screens(self):
        response = self.post({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'events_list', 'arguments': {}}},
                             {'Authorization': self.tokens[self.outsider]})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.error('events_list', {}, self.staff).startswith('Not permitted'))
        self.assertTrue(self.error('knowledge_save', {'values': {'title': 'Staff', 'instructions': 'x'}, 'request_key': 'staff-key-01'},
                                   self.staff).startswith('Not permitted'))
        self.assertTrue(self.error('skills_options', {'kind': 'report', 'business_doctype': 'Customer'}, self.staff).startswith('Not permitted'))
        self.assertFalse(self.tool('skills_options', {'kind': 'business_doctype'}, self.staff)['isError'])

    def test_event_save_queues_the_memory_build_and_shows_on_the_events_screen(self):
        import frappe
        from relay_core.ai import events
        values = {'title': 'MCP Fair ' + self.stamp, 'enabled': 1, 'description': 'Fair on the first of December.',
                  'event_starts_on': '2026-12-01', 'audience': AUDIENCE}
        key = 'event-' + self.stamp
        name = self.tool('events_save', {'values': values, 'request_key': key})['structuredContent']['name']
        self.created.append(('Relay AI Event', name))
        self.assertEqual(self.tool('events_save', {'values': values, 'request_key': key})['structuredContent']['name'], name)
        builds = [call.kwargs for call in frappe.enqueue.call_args_list
                  if call.args[:1] == ('relay_core.ai.event_memory.build',)]
        self.assertEqual([build['relay_event'] for build in builds], [name])
        listed = {row.name: row for row in self.as_manager(events.directory)['items']}
        self.assertEqual((listed[name].memory_status, listed[name].audience), ('Pending', AUDIENCE))
        self.assertEqual(self.tool('events_status', {'name': name})['structuredContent']['memory_status'], 'Pending')
        self.assertIn('ends before it starts', self.error('events_save', {'values': dict(values, event_ends_on='2026-11-01'),
                                                                          'name': name}))
        self.assertIn('request_key is required', self.error('events_save', {'values': values}))

    def test_attach_adds_links_and_files_within_the_limits(self):
        import frappe
        from relay_core.attachments import save_attachment
        self.assertEqual(self.error('events_save', {'values': {'title': 'No text', 'audience': AUDIENCE}, 'request_key': 'no-text-01'}),
                         'Fill in the required fields: description')
        name = self.save('events_save', {'title': 'MCP Catalog ' + self.stamp, 'description': 'Catalog.', 'audience': AUDIENCE})

        def attach(**arguments):
            return self.tool('events_attach', {'name': name, 'request_key': 'attach-' + secrets.token_hex(8), **arguments})
        event = attach(url='https://example.test/catalog', note='Catalog')['structuredContent']
        self.assertEqual(event['links'], [{'url': 'https://example.test/catalog', 'note': 'Catalog'}])
        self.assertIn('http or https', attach(url='ftp://example.test/x')['content'][0]['text'])
        text = base64.b64encode(b'Price list').decode()
        self.assertIn('Attach one of these file types', attach(filename='tool.exe', content_base64=text)['content'][0]['text'])
        self.assertEqual(attach(filename='bad.txt', content_base64='not base64!')['content'][0]['text'], 'Invalid file data')
        with patch('relay_core.ai.event_memory.file_limit', return_value=4):
            self.assertIn('must be at most', attach(filename='big.txt', content_base64=text)['content'][0]['text'])
        self.assertEqual(attach(filename='prices.txt', content_base64=text)['structuredContent']['files'][0]['file_name'], 'prices.txt')
        frappe.set_user('Administrator')
        for index in range(9):
            save_attachment(f'sheet-{index}.txt', b'Row', name, 'Relay AI Event')
        frappe.db.commit()
        self.assertIn('at most 10 files', attach(filename='eleventh.txt', content_base64=text)['content'][0]['text'])
        self.assertEqual(len(self.tool('events_read', {'name': name})['structuredContent']['files']), 10)

    def test_knowledge_save_shows_on_the_knowledge_screen(self):
        from relay_core.ai import knowledge
        name = self.save('knowledge_save', {'title': 'MCP Returns ' + self.stamp, 'enabled': 1,
                                            'instructions': 'Accept returns within 7 days.'})
        self.assertIn(name, [row.name for row in self.as_manager(knowledge.directory)['items']])
        self.assertEqual(self.tool('knowledge_read', {'name': name})['structuredContent']['instructions'], 'Accept returns within 7 days.')
        self.assertEqual(self.error('knowledge_save', {'values': {'instructions': '   '}, 'name': name}),
                         'Use 1–8000 instruction characters')

    def test_skill_saved_over_mcp_equals_the_skills_screen_save(self):
        import frappe
        from relay_core.ai import configuration
        capability = self.tool('skills_options', {'kind': 'report', 'business_doctype': 'Customer'})['structuredContent']['items'][0]['value']
        values = {'business_doctype': 'Customer', 'instructions': 'Answer questions about the ledger.', 'target': 'Ledger questions',
                  'allowed_tools': [{'capability': capability}]}
        self.assertEqual(self.tool('skills_validate', {'values': dict(values, title='x')})['structuredContent'],
                         {'valid': True, 'problems': []})
        name = self.save('skills_save', dict(values, title='MCP Ledger ' + self.stamp))
        screen = dict(values, title='UI Ledger ' + self.stamp, mode='Shadow', enabled=0, allowed_tools=json.dumps(values['allowed_tools']))
        other = self.as_manager(configuration.save, screen)['name']
        self.created.append(('Relay AI Skill', other))
        fields = [field for field in configuration.FIELDS if field != 'title']
        saved = [frappe.get_doc('Relay AI Skill', skill).as_dict() for skill in (name, other)]
        self.assertEqual(*[{field: row[field] for field in fields} for row in saved])
        read = self.tool('skills_read', {'name': name})['structuredContent']
        self.assertEqual((read['mode'], read['enabled'], read['allowed_tools']), ('Shadow', 0, values['allowed_tools']))
        self.assertIn(name, [row['name'] for row in self.tool('skills_list', {})['structuredContent']['items']])
        self.assertIn(name, [row.name for row in self.as_manager(configuration.directory)['items']])

    def test_skill_rules_surface_as_clear_errors(self):
        values = {'title': 'MCP Rules ' + self.stamp, 'business_doctype': 'Customer', 'instructions': 'Answer.', 'target': 'Any'}
        result = self.tool('skills_validate', {'values': dict(values, allowed_actions=[{'action': 'reply'}])})['structuredContent']
        self.assertEqual(result, {'valid': False, 'problems': ['Ticket only events cannot declare actions']})
        result = self.tool('skills_validate', {'values': {'instructions': 'Answer.'}})['structuredContent']
        self.assertFalse(result['valid'])
        self.assertTrue(any('Title' in problem for problem in result['problems']), result)
        live = dict(values, enabled=1, mode='Automatic')
        self.assertIn('pass confirm: true', self.error('skills_save', {'values': live, 'request_key': 'live-' + self.stamp}))
        self.assertIn('identity is required', self.error('skills_save', {'values': live, 'request_key': 'live-' + self.stamp,
                                                                         'confirm': True}))


if __name__ == '__main__':
    unittest.main()
