"""reply_context: the business record, company, sections behind read permission and the event and knowledge rules."""
import unittest
from unittest.mock import Mock, patch

import frappe

from relay_core import reply_context

CON = 'RELAY-CON-0000000001'


def message(name, direction='Incoming', **values):
    return frappe._dict({'name': name, 'direction': direction, 'channel': 'RELAY-CH-0000000001', 'business_doctype': None,
                         'business_name': None, **values})


class ReadTests(unittest.TestCase):
    def read(self, rows, readable=('Relay AI Persona', 'Relay AI Event', 'Relay AI Playbook'), primary=None):
        profile = {'name': CON, 'display_name': 'Sample Contact', 'primary': primary}
        database = Mock()
        database.get_value.return_value = 'Example Co'
        with patch('relay_core.api.contact_profile', return_value=profile), \
                patch('relay_core.api.messages', return_value={'items': rows, 'has_more': False}) as messages, \
                patch.object(frappe, 'db', database), \
                patch.object(frappe, 'has_permission', side_effect=lambda doctype, *args, **kwargs: doctype in readable), \
                patch.object(reply_context, 'record_summary', side_effect=lambda doctype, name: {'doctype': doctype, 'name': name}), \
                patch.object(reply_context, 'persona_of', return_value={'persona_name': 'Mira'}) as persona, \
                patch.object(reply_context, 'events_of', return_value=[{'title': 'Fair'}]) as events, \
                patch.object(reply_context, 'knowledge_of', return_value=[{'title': 'Returns'}]) as knowledge, \
                patch('relay_core.messaging.reply_window', return_value={'open': True}) as window:
            result = reply_context.read(CON, 5)
        messages.assert_called_once_with(CON, limit=5)
        return result, dict(persona=persona, events=events, knowledge=knowledge, window=window)

    def test_the_newest_message_gives_the_record_and_the_company(self):
        rows = [message('RELAY-MSG-0000000001'), message('RELAY-MSG-0000000002', 'Outgoing', business_doctype='Customer',
                                                         business_name='CUST-0001')]
        result, calls = self.read(rows, primary={'doctype': 'Customer', 'name': 'CUST-0002'})
        self.assertEqual((result['company'], result['business_record']), ('Example Co', {'doctype': 'Customer', 'name': 'CUST-0001'}))
        self.assertEqual((result['persona'], result['events'], result['knowledge']),
                         ({'persona_name': 'Mira'}, [{'title': 'Fair'}], [{'title': 'Returns'}]))
        calls['events'].assert_called_once_with(('Customer', 'CUST-0001'), 'Example Co')
        calls['window'].assert_called_once_with('RELAY-MSG-0000000001')
        self.assertEqual(result['reply_window'], {'open': True})

    def test_without_a_message_record_the_primary_record_is_used(self):
        result, _ = self.read([message('RELAY-MSG-0000000001')], primary={'doctype': 'Customer', 'name': 'CUST-0002'})
        self.assertEqual(result['business_record'], {'doctype': 'Customer', 'name': 'CUST-0002'})

    def test_sections_the_user_cannot_read_are_null_and_never_loaded(self):
        result, calls = self.read([], readable=())
        self.assertEqual((result['persona'], result['events'], result['knowledge'], result['business_record'], result['company']),
                         (None, None, None, None, None))
        for name in ('persona', 'events', 'knowledge', 'window'):
            calls[name].assert_not_called()
        self.assertEqual(result['reply_window'], {'open': False})


class SectionTests(unittest.TestCase):
    def test_events_use_the_ai_rules_with_the_user_permissions_and_no_files(self):
        row = frappe._dict(name='Fair-001', title='Fair', description='Fair on the first.', company=None, available_from=None,
                           available_to=None, event_starts_on=None, event_ends_on=None, memory='built memory')
        with patch.object(reply_context, 'available_events', return_value=[row] * 5) as available:
            events = reply_context.events_of(('Customer', 'CUST-0001'), 'Example Co')
        self.assertEqual(available.call_args.args, ('Customer', 'Example Co'))
        self.assertEqual(available.call_args.kwargs, {'fields': ('description',), 'reader': frappe.get_list})
        self.assertEqual(len(events), reply_context.MAX_EVENTS)
        self.assertEqual(set(events[0]), {'name', 'title', 'description', 'event_starts_on', 'event_ends_on', 'available_to'})
        self.assertEqual(reply_context.events_of(None, 'Example Co'), [])

    def test_knowledge_applies_by_company_and_business_type_like_the_ai(self):
        rows = [frappe._dict(title='All', instructions='Be brief.', company='', business_doctype=''),
                frappe._dict(title='Other company', instructions='x', company='Other Co', business_doctype=''),
                frappe._dict(title='Suppliers', instructions='y', company='', business_doctype='Supplier')]
        reader = Mock(return_value=rows)
        with patch.object(frappe, 'get_list', reader):
            self.assertEqual(reply_context.knowledge_of(('Customer', 'CUST-0001'), 'Example Co'),
                             [{'title': 'All', 'instructions': 'Be brief.'}])
            self.assertEqual([row['title'] for row in reply_context.knowledge_of(None, 'Other Co')], ['All', 'Other company'])

    def test_record_summary_needs_the_business_type_and_record_permission(self):
        with patch('relay_core.business_access.allowed_types', return_value={'Customer'}), \
                patch.object(frappe, 'has_permission', return_value=False):
            self.assertIsNone(reply_context.record_summary('Supplier', 'SUP-0001'))
            self.assertIsNone(reply_context.record_summary('Customer', 'CUST-0001'))
        fields = [frappe._dict(fieldname='customer_group', label='Customer Group', fieldtype='Link', in_list_view=1),
                  frappe._dict(fieldname='items', label='Items', fieldtype='Table', in_list_view=1),
                  frappe._dict(fieldname='notes', label='Notes', fieldtype='Text', in_list_view=0)]
        doc = Mock()
        doc.get.side_effect = {'customer_name': 'Sample Traders', 'customer_group': 'Retail', 'items': [1], 'notes': 'x'}.get
        with patch('relay_core.business_access.allowed_types', return_value={'Customer'}), \
                patch('relay_core.business_groups.title_field', return_value='customer_name'), \
                patch.object(frappe, 'has_permission', return_value=True), patch.object(frappe, 'get_doc', return_value=doc), \
                patch.object(frappe, 'get_meta', return_value=frappe._dict(fields=fields)):
            summary = reply_context.record_summary('Customer', 'CUST-0001')
        doc.apply_fieldlevel_read_permissions.assert_called_once_with()
        self.assertEqual(summary, {'doctype': 'Customer', 'name': 'CUST-0001', 'title': 'Sample Traders',
                                   'fields': [{'label': 'Customer Group', 'value': 'Retail'}]})

    def test_persona_is_read_with_the_user_permissions(self):
        with patch('relay_core.ai.persona.find', return_value=frappe._dict(persona_name='Mira', instructions=None)) as find:
            self.assertEqual(reply_context.persona_of('Example Co'), {'persona_name': 'Mira', 'instructions': ''})
        find.assert_called_once_with('Example Co', frappe.get_list)


if __name__ == '__main__':
    unittest.main()
