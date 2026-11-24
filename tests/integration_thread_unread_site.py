"""Per-thread unread counts on relay.test with real SQL: reading one thread never hides an older unread thread, and a
rebuild counts the same way. Runs inside one transaction that is always rolled back.

Run from the bench sites folder: ../env/bin/python -B -m unittest discover -s <app>/tests -p 'integration_thread_unread_site.py'"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frappe


class ThreadUnreadSiteTests(unittest.TestCase):
    def setUp(self):
        frappe.init(site=os.environ.get('RELAY_TEST_SITE', 'relay.test'), sites_path=os.environ['SITES_PATH'])
        frappe.connect()
        frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0
        self.enterContext(patch.object(frappe, 'publish_realtime'))
        self.enterContext(patch.object(frappe, 'enqueue'))
        self.addCleanup(frappe.destroy)
        self.addCleanup(frappe.db.rollback)
        tag = frappe.generate_hash(length=6)
        customer = frappe.get_doc({'doctype': 'Customer', 'customer_name': 'Local thread unread ' + tag, 'customer_type': 'Company',
                                   'gst_category': 'Unregistered'}).insert()
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Local thread unread ' + tag,
                                 'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]}).insert()
        self.contact = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name, 'display_name': person.first_name}).insert().name
        self.channel = frappe.get_doc({'doctype': 'Relay Channel', 'title': 'Local thread unread ' + tag, 'channel': 'Email',
                                       'account': 'local-thread-unread', 'enabled': 0, 'mailbox_address': tag + '@example.invalid'}).insert().name
        self.key = ('Customer', customer.name)

    def message(self, endpoint, direction='Incoming'):
        text = 'Local thread unread ' + endpoint
        return frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': self.contact, 'channel': self.channel, 'direction': direction,
            'content': text, 'sender_endpoint': endpoint, 'message_type': 'text', 'business_doctype': self.key[0], 'business_name': self.key[1],
            'message_data': json.dumps({'kind': 'text', 'text': text})}).insert().name

    def read(self, name):
        """What business_inbox.mark_visible does."""
        from relay_core import relay_chats
        from relay_core.message_reads import insert_reads
        insert_reads([(self.contact, name)])
        relay_chats.mark_read(self.key)

    def counts(self):
        from relay_core import relay_chats
        from relay_core.conversation_threads import threads
        chat = frappe.db.get_value(relay_chats.CHAT, {'business_doctype': self.key[0], 'business_name': self.key[1]}, 'unread_count')
        tabs = {item['endpoint']: item['unread'] for item in threads(doctype=self.key[0], name=self.key[1])['items']}
        return chat, tabs

    def test_reading_one_thread_keeps_an_older_unread_thread(self):
        self.message('a@example.invalid')
        self.read(self.message('b@example.invalid'))
        self.assertEqual(self.counts(), (1, {'a@example.invalid': 1, 'b@example.invalid': 0}))
        self.read(self.message('b@example.invalid'))
        self.assertEqual(self.counts(), (1, {'a@example.invalid': 1, 'b@example.invalid': 0}), 'A1 is never lost')
        from relay_core import relay_chats
        self.assertEqual(relay_chats.unread_counts(relay_chats.unstamped_owners()).get(self.key), 1, 'A rebuild counts the same')

    def test_a_reply_answers_only_its_thread_and_mark_all_read_reads_every_thread(self):
        from relay_core import relay_chats
        self.message('a@example.invalid')
        self.message('b@example.invalid')
        self.message('b@example.invalid', 'Outgoing')
        self.assertEqual(self.counts(), (1, {'a@example.invalid': 1, 'b@example.invalid': 0}))
        relay_chats.mark_read(self.key, everything=True)
        self.assertEqual(self.counts(), (0, {'a@example.invalid': 0, 'b@example.invalid': 0}))


if __name__ == '__main__':
    unittest.main()
