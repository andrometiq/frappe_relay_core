import unittest
from unittest.mock import patch

import frappe
from frappe import _dict
from relay_core import realtime


class ConversationEventNames(unittest.TestCase):
    """Open threads re-read only the messages a conversation event names."""

    def setUp(self):
        self.publish = self.enterContext(patch.object(frappe, 'publish_realtime'))
        self.enterContext(patch.object(frappe.realtime, 'get_doctype_room', side_effect=lambda doctype: 'room:' + doctype))
        self.enterContext(patch('relay_core.queue_counts.invalidate'))

    def events(self):
        return [(call.args[1], call.kwargs.get('docname') or call.kwargs.get('room')) for call in self.publish.call_args_list]

    def test_message_change_names_the_message_only_in_conversation_rooms(self):
        doc = _dict(doctype='Relay Message', name='RELAY-MSG-0000000002', relay_contact='RELAY-CON-0000000001',
                    business_doctype='Customer', business_name='CUST-1', content='private body')
        realtime.changed(doc)
        self.assertEqual(self.events(), [
            ({'kind': 'messages'}, 'room:Relay Message'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002']}, 'RELAY-CON-0000000001'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002']}, 'CUST-1'),
        ])
        self.assertNotIn('private body', repr(self.publish.call_args_list))

    def test_batch_names_every_changed_message_once(self):
        realtime.contact_changed('RELAY-CON-0000000001', messages=['RELAY-MSG-0000000003', 'RELAY-MSG-0000000001', 'RELAY-MSG-0000000003'])
        self.assertEqual(self.events(), [({'kind': 'messages', 'messages': ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000003']}, 'RELAY-CON-0000000001')])

    def test_other_changes_carry_no_names(self):
        realtime.changed(_dict(doctype='Relay Contact', name='RELAY-CON-0000000001'))
        realtime.contact_changed('RELAY-CON-0000000001', 'reads')
        self.assertEqual([event for event, _ in self.events()], [{'kind': 'contacts'}, {'kind': 'reads'}])


if __name__ == '__main__':
    unittest.main()
