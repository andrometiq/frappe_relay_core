"""One person writing to two business numbers stays one Relay Contact with one endpoint per number."""
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from channel_fakes import FakeSite
from relay_core import contact_lifecycle
from relay_core.automation import projection

NUMBER = '919999999999'


def key(channel, value):
    return hashlib.sha256((channel + ':' + value).encode()).hexdigest()


def site(*endpoints, channels=None):
    rows = channels or [
        {'name': 'Shop', 'channel': 'WhatsApp', 'account': 'site-a', 'enabled': 1},
        {'name': 'Support', 'channel': 'WhatsApp', 'account': 'site-a', 'enabled': 1},
        {'name': 'Bot', 'channel': 'Telegram', 'account': 'site-a', 'enabled': 1},
        {'name': 'Other site', 'channel': 'WhatsApp', 'account': 'site-b', 'enabled': 1}]
    endpoints = [dict(row, endpoint_key=key(row['channel'], row['endpoint'])) for row in endpoints]
    return FakeSite(Relay_Channel=rows, Relay_Contact_Endpoint=endpoints, on_insert={
        'Relay Contact Endpoint': lambda row: row.update(endpoint_key=key(row['channel'], row['endpoint']))})


class SiblingContactTests(unittest.TestCase):
    def bind(self, fake, channel='Support', endpoint=NUMBER):
        with patch.object(contact_lifecycle, 'frappe', fake.frappe), patch('frappe.get_all', fake.get_all):
            return contact_lifecycle.sibling_contact(channel, endpoint)

    def test_same_customer_on_two_numbers_is_one_contact_with_two_endpoints(self):
        fake = site({'channel': 'Shop', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 1})
        self.assertEqual(self.bind(fake), 'C1')
        endpoints = fake.rows('Relay Contact Endpoint', {'relay_contact': 'C1', 'verified': 1})
        self.assertEqual(sorted(row.channel for row in endpoints), ['Shop', 'Support'])
        self.assertEqual(self.bind(fake), 'C1')
        self.assertEqual(len(fake.rows('Relay Contact Endpoint')), 2)

    def test_identity_of_two_contacts_or_unknown_sender_stays_in_triage(self):
        shared = site({'channel': 'Shop', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 1},
                      {'channel': 'Bot', 'endpoint': '5', 'relay_contact': 'C9', 'verified': 1},
                      {'channel': 'Other site', 'endpoint': NUMBER, 'relay_contact': 'C2', 'verified': 1})
        self.assertEqual(self.bind(shared), 'C1')  # Other sites and other channel types do not count.
        two = site({'channel': 'Shop', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 1},
                   {'channel': 'Spare', 'endpoint': NUMBER, 'relay_contact': 'C2', 'verified': 1},
                   channels=[{'name': name, 'channel': 'WhatsApp', 'account': 'site-a'} for name in ('Shop', 'Spare', 'Support')])
        self.assertIsNone(self.bind(two))
        self.assertIsNone(self.bind(site()))
        unverified = site({'channel': 'Shop', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 0})
        self.assertIsNone(self.bind(unverified))

    def test_a_revoked_binding_on_the_new_number_is_not_replaced(self):
        fake = site({'channel': 'Shop', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 1},
                    {'channel': 'Support', 'endpoint': NUMBER, 'relay_contact': 'C1', 'verified': 0})
        self.assertIsNone(self.bind(fake))
        self.assertEqual(len(fake.rows('Relay Contact Endpoint')), 2)

    def test_groups_never_bind_across_channels(self):
        fake = site({'channel': 'Shop', 'endpoint': 'group-id', 'relay_contact': 'C1', 'verified': 1})
        self.assertIsNone(self.bind(fake, endpoint='group-id'))


class ProjectionBindingTests(unittest.TestCase):
    def project(self, message, ai=True):
        payload = {'entry': [{'changes': [{'value': {'messages': [message]}}]}]}
        event = _dict(name='event', account='site-a', projection_status='Pending', payload=json.dumps(payload))
        fake = Mock()
        fake.get_doc.return_value = event
        fake.db.exists.return_value = False
        fake.db.get_value.return_value = None
        with patch.object(projection, 'frappe', fake), patch('relay_core.hub_channels.event_channel', return_value='Support'), \
                patch.object(projection, 'apply_updates', return_value='Ignored'), \
                patch('relay_core.whatsapp_templates.project', return_value=False), \
                patch('relay_core.call_records.ingest', return_value=False), patch('relay_core.bulk_updates.link_reply'), \
                patch('relay_core.realtime.changed'), patch('relay_core.tickets.ensure_episode') as triage, \
                patch('relay_core.ai_features.is_enabled', return_value=ai), \
                patch.object(contact_lifecycle, 'sibling_contact', return_value=None) as sibling, \
                patch.object(contact_lifecycle, 'whatsapp_contact', return_value=None):
            projection.project('event')
        return sibling, triage

    def test_ai_off_opens_no_triage_ticket(self):
        _, triage = self.project({'id': 'm1', 'from': NUMBER, 'group_id': 'g1', 'type': 'text', 'text': {'body': 'Hi'}}, ai=False)
        triage.assert_not_called()

    def test_a_private_sender_without_endpoint_is_matched_across_numbers_first(self):
        sibling, triage = self.project({'id': 'm1', 'from': NUMBER, 'type': 'text', 'text': {'body': 'Hi'}})
        sibling.assert_called_once_with('Support', NUMBER)
        triage.assert_called_once()

    def test_a_group_sender_goes_to_triage_directly(self):
        sibling, triage = self.project({'id': 'm1', 'from': NUMBER, 'group_id': 'g1', 'type': 'text', 'text': {'body': 'Hi'}})
        sibling.assert_not_called()
        triage.assert_called_once()


if __name__ == '__main__':
    unittest.main()
