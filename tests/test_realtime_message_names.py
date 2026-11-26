import unittest
from unittest.mock import patch

import frappe
from frappe import _dict
from relay_core import realtime


class ConversationEventNames(unittest.TestCase):
    """Open threads re-read only the messages a conversation event names."""

    def setUp(self):
        self.publish = self.enterContext(patch.object(frappe, 'publish_realtime'))
        self.enterContext(patch('frappe.permissions.get_doctype_roles', side_effect=lambda doctype, ptype='read': ['reader:' + doctype]))
        self.enterContext(patch.object(frappe, 'get_all', return_value=['agent@example.com']))
        self.enterContext(patch('relay_core.queue_counts.invalidate'))
        self.enterContext(patch.object(realtime.secrets, 'token_hex', side_effect=['c1', 'c2', 'c3']))

    def events(self):
        return [(call.args[1], call.kwargs.get('docname') or call.kwargs.get('user')) for call in self.publish.call_args_list]

    def test_message_change_names_the_message_only_in_conversation_rooms(self):
        doc = _dict(doctype='Relay Message', name='RELAY-MSG-0000000002', relay_contact='RELAY-CON-0000000001',
                    business_doctype='Customer', business_name='CUST-1', content='private body')
        realtime.changed(doc)
        # One change key in every room: a chat list matches the shared event to the open conversation's event.
        self.assertEqual(self.events(), [
            ({'kind': 'messages', 'change': 'c1'}, 'Administrator'),
            ({'kind': 'messages', 'change': 'c1'}, 'agent@example.com'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002'], 'change': 'c1'}, 'RELAY-CON-0000000001'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002'], 'change': 'c1'}, 'CUST-1'),
        ])
        self.assertNotIn('private body', repr(self.publish.call_args_list))
        realtime.changed(doc)
        self.assertEqual({event['change'] for event, _ in self.events()[4:]}, {'c2'})

    def test_batch_names_every_changed_message_once(self):
        realtime.contact_changed('RELAY-CON-0000000001', messages=['RELAY-MSG-0000000003', 'RELAY-MSG-0000000001', 'RELAY-MSG-0000000003'])
        self.assertEqual(self.events(), [({'kind': 'messages', 'messages': ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000003'],
                                           'change': 'c1'}, 'RELAY-CON-0000000001')])

    def test_receipt_change_is_marked_in_every_room_and_keeps_counts(self):
        doc = _dict(doctype='Relay Message', name='RELAY-MSG-0000000002', relay_contact='RELAY-CON-0000000001',
                    business_doctype='Customer', business_name='CUST-1')
        with patch('relay_core.queue_counts.invalidate') as invalidate:
            realtime.changed(doc, receipt=True)
        self.assertEqual(self.events(), [
            ({'kind': 'messages', 'change': 'c1', 'receipt': 1}, 'Administrator'),
            ({'kind': 'messages', 'change': 'c1', 'receipt': 1}, 'agent@example.com'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002'], 'change': 'c1', 'receipt': 1}, 'RELAY-CON-0000000001'),
            ({'kind': 'messages', 'messages': ['RELAY-MSG-0000000002'], 'change': 'c1', 'receipt': 1}, 'CUST-1'),
        ])
        invalidate.assert_not_called()

    def test_other_changes_carry_no_names(self):
        realtime.changed(_dict(doctype='Relay Contact', name='RELAY-CON-0000000001'))
        realtime.contact_changed('RELAY-CON-0000000001', 'reads')
        self.assertEqual([event for event, _ in self.events()], [{'kind': 'contacts'}, {'kind': 'contacts'}, {'kind': 'reads'}])

    def test_shared_changes_reach_each_reader_without_a_doctype_room(self):
        """A site may refuse whole-DocType rooms to a user, so a chat list must not depend on joining one."""
        realtime.changed(_dict(doctype='Relay Message', name='RELAY-MSG-0000000002'))
        self.assertEqual(frappe.get_all.call_args.kwargs['filters']['role'], ['in', ['reader:Relay Message']])
        self.assertEqual([call.kwargs for call in self.publish.call_args_list], [
            {'user': 'Administrator', 'after_commit': True}, {'user': 'agent@example.com', 'after_commit': True}])

    def test_a_notification_change_reaches_only_its_user(self):
        realtime.changed(_dict(doctype='Relay Notification', name='RELAY-NOT-1', user='agent@example.com',
                               relay_contact='RELAY-CON-0000000001', kind='Mention'))
        self.assertEqual(self.publish.call_count, 1)
        self.assertEqual(self.publish.call_args.args, ('relay_changed', {'kind': 'notifications'}))
        self.assertEqual(self.publish.call_args.kwargs, {'user': 'agent@example.com', 'after_commit': True})
        self.publish.reset_mock()
        realtime.changed(_dict(doctype='Relay Notification', name='RELAY-NOT-2', user=None))
        self.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
