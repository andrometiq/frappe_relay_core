"""Customer poll notice patch: old poll rows get the new notice in message_data only, once. No site data is touched."""
import json
import unittest
from unittest.mock import Mock, patch

from frappe import _dict

from relay_core.message_types import POLL_REASONS
from relay_core.patches.v1_0 import show_customer_poll_notice as module

META_ERROR = [{'code': 131051, 'title': 'Message type unknown'}]


def poll_event(message_id, kind):
    message = {'id': message_id, 'from': '919999999999', 'type': 'unsupported', 'errors': META_ERROR,
               'unsupported': {'type': kind}}
    return json.dumps({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})


class CustomerPollNoticePatchTests(unittest.TestCase):
    def run_patch(self, messages, events):
        updates = []

        def get_all(doctype, **kwargs):
            if doctype == 'Relay Hub Event':
                return events
            if doctype == 'Relay Channel':
                return ['WhatsApp Sales']
            return [_dict(row) for row in messages]

        def set_value(doctype, name, field, value, update_modified=True):
            updates.append((name, field, json.loads(value), update_modified))
            next(row for row in messages if row['name'] == name)['message_data'] = value

        fake = Mock(get_all=get_all)
        fake.db.set_value = set_value
        with patch.object(module, 'frappe', fake):
            module.execute()
        return updates

    def test_old_poll_rows_get_the_notice_once(self):
        messages = [
            {'name': 'MSG-1', 'provider_id': 'wamid.one', 'message_data': json.dumps({'kind': 'unsupported'})},
            {'name': 'MSG-2', 'provider_id': 'wamid.two', 'message_data': json.dumps({'kind': 'unsupported',
                'unsupported': {'type': 'poll_update', 'code': 131051, 'reason': 'Poll vote messages are not supported by WhatsApp Business'}})},
            {'name': 'MSG-3', 'provider_id': 'wamid.three', 'message_data': json.dumps({'kind': 'unsupported',
                'unsupported': {'type': 'group_invite', 'reason': 'Group invite messages are not supported by WhatsApp Business'}})},
        ]
        updates = self.run_patch(messages, [poll_event('wamid.one', 'poll_creation'), 'not json'])
        self.assertEqual([(name, field, modified) for name, field, _, modified in updates],
                         [('MSG-1', 'message_data', False), ('MSG-2', 'message_data', False)])
        first, second = updates[0][2], updates[1][2]
        self.assertEqual(first['unsupported']['type'], 'poll_creation')
        self.assertEqual(first['unsupported']['code'], 131051)
        self.assertEqual(first['unsupported']['reason'], POLL_REASONS['poll_creation'])
        self.assertEqual(second['unsupported'], {'type': 'poll_update', 'code': 131051, 'reason': POLL_REASONS['poll_update']})
        self.assertEqual(self.run_patch(messages, [poll_event('wamid.one', 'poll_creation')]), [], 'A second run changes nothing')


if __name__ == '__main__':
    unittest.main()
