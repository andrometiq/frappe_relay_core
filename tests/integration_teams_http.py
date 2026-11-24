"""Local relay.test HTTP acceptance of team record scope and tickets without a chat: shapes, allowed and denied users.

Run from the app folder: SITES_PATH=../../sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_teams_http.py'
Needs Customer records on relay.test, some in the Government group and some without a group. Fixture users are reusable;
the team, tickets, Teams switch and Customer grouping are restored afterwards. API credentials are ephemeral.
"""
import json
import os
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import frappe
import frappe.app
import requests
from integration_access_http import Quiet, connect, remove_from_types, user_with_key

USER, MANAGER = 'Relay Communication User', 'Relay Communication Manager'
TEAM = 'Relay Teams Fixture Team'
PICKED_TEAM = 'Relay Teams Fixture Picked'
GROUP = 'Government'
GROUP_ROW = {'business_doctype': 'Customer', 'access': 'Group', 'value': GROUP, 'grouping_field': 'customer_group'}


class TeamsHttpTests(unittest.TestCase):
    MANAGER_USER, AGENT, MENTIONED, OUTSIDER = (
        'relay-teams-manager@example.invalid', 'relay-teams-agent@example.invalid',
        'relay-teams-mentioned@example.invalid', 'relay-teams-outsider@example.invalid')

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.manager = user_with_key(cls.MANAGER_USER, 'Local teams manager', [MANAGER])
        cls.agent = user_with_key(cls.AGENT, 'Local teams agent', [USER])
        cls.mentioned = user_with_key(cls.MENTIONED, 'Local teams mentioned', [USER])
        cls.outsider = user_with_key(cls.OUTSIDER, 'Local teams outsider', [USER])
        for user in (cls.AGENT, cls.MENTIONED, cls.OUTSIDER):
            remove_from_types(user)
        cls.grouped = frappe.get_all('Customer', filters={'customer_group': GROUP}, pluck='name', order_by='name', limit=2)
        cls.ungrouped = frappe.get_all('Customer', filters={'customer_group': ['is', 'not set']}, pluck='name', order_by='name', limit=2)
        if len(cls.grouped) < 1 or len(cls.ungrouped) < 2:
            raise unittest.SkipTest('relay.test needs Customers in the Government group and without a group')
        config = frappe.get_doc('Relay Contact Type', 'Customer')
        cls.grouping = [{'fieldname': row.fieldname, 'priority': row.priority} for row in config.grouping_fields]
        config.set('grouping_fields', [{'fieldname': 'customer_group', 'priority': 1}])
        config.save()
        cls.teams_were_on = frappe.db.get_single_value('Relay Settings', 'enable_teams')
        frappe.db.set_single_value('Relay Settings', 'enable_teams', 1)
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.'
        cls.chat = cls.chat_without_records()
        team = cls.post('teams.save', cls.manager, title=TEAM, members=[cls.AGENT], business=[GROUP_ROW])
        team.raise_for_status()
        cls.team = team.json()['message']['name']
        picked = cls.post('teams.save', cls.manager, title=PICKED_TEAM, members=[cls.AGENT, cls.MENTIONED], business=[
            {'business_doctype': 'Customer', 'access': 'Record', 'value': cls.ungrouped[0]}])
        picked.raise_for_status()
        cls.picked_team = picked.json()['message']['name']

    @classmethod
    def chat_without_records(cls):
        """A WhatsApp chat of a new contact without business links: [channel, Contact, Relay Contact, message]."""
        connect()
        try:
            created = []
            def insert(values):
                created.append(frappe.get_doc(values).insert(ignore_permissions=True))
                return created[-1]
            channel = insert({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': 'relay-teams-fixture', 'enabled': 1})
            person = insert({'doctype': 'Contact', 'first_name': 'Relay teams fixture person'})
            relay = insert({'doctype': 'Relay Contact', 'display_name': person.first_name, 'contact': person.name})
            insert({'doctype': 'Relay Message', 'relay_contact': relay.name, 'channel': channel.name, 'direction': 'Incoming',
                    'status': 'Sent', 'content': 'Please send the new price list', 'sender_endpoint': '15550001234',
                    'message_type': 'text'})
            frappe.db.commit()
            return [(doc.doctype, doc.name) for doc in created]
        finally:
            frappe.destroy()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        for name in frappe.get_all('Relay Ticket', filters={'subject': ['like', 'Relay teams fixture%']}, pluck='name'):
            frappe.delete_doc('Relay Ticket', name, ignore_permissions=True, force=True)
        for team in (getattr(cls, 'team', None), getattr(cls, 'picked_team', None)):
            if team:
                frappe.delete_doc('Relay Team', team, ignore_permissions=True, force=True)
        for doctype, name in reversed(getattr(cls, 'chat', [])):
            for ticket in frappe.get_all('Relay Ticket Message', filters={'message': name}, pluck='parent') if doctype == 'Relay Message' else []:
                frappe.delete_doc('Relay Ticket', ticket, ignore_permissions=True, force=True)
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
        config = frappe.get_doc('Relay Contact Type', 'Customer')
        config.set('grouping_fields', cls.grouping)
        config.save()
        frappe.db.set_single_value('Relay Settings', 'enable_teams', cls.teams_were_on or 0)
        for email in (cls.MANAGER_USER, cls.AGENT, cls.MENTIONED, cls.OUTSIDER):
            user = frappe.get_doc('User', email)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    @classmethod
    def post(cls, method, headers, **values):
        return requests.post(cls.url + method, json=values, headers=headers, timeout=30)

    def get(self, method, headers, **values):
        return requests.get(self.url + method, params=values, headers=headers, timeout=30)

    def ticket(self, headers, record, **values):
        return self.post('tickets.create', headers, subject='Relay teams fixture ticket', business_type='Customer',
                         business_record=record, **values)

    def test_manager_lists_teams_with_members_and_access_and_users_are_denied(self):
        response = self.get('teams.directory', self.manager, query=TEAM)
        self.assertEqual(response.status_code, 200)
        [row] = [row for row in response.json()['message']['items'] if row['name'] == self.team]
        self.assertEqual(row['members'], [self.AGENT])
        self.assertEqual(row['business'], [{'business_doctype': 'Customer', 'all': False, 'groups': 1, 'records': 0}])
        self.assertTrue(response.json()['message']['teams_enabled'])
        read = self.get('teams.read', self.manager, name=self.team).json()['message']
        self.assertEqual(read['business'], [GROUP_ROW])
        self.assertEqual(self.get('teams.directory', self.agent).status_code, 403)
        denied = self.post('teams.save', self.agent, title='Relay teams fixture denied', members=[self.AGENT])
        self.assertEqual(denied.status_code, 403)
        invalid = self.post('teams.save', self.manager, name=self.team, title=TEAM, members=[self.AGENT],
                            business=[{'business_doctype': 'Customer', 'access': 'Record', 'value': 'No such customer'}])
        self.assertEqual(invalid.status_code, 417)

    def test_a_stale_grouping_field_or_a_repeated_type_is_refused(self):
        cases = {'Pick its groups again': [{**GROUP_ROW, 'grouping_field': ''}],
                 'grouping field of Customer changed': [{**GROUP_ROW, 'grouping_field': 'territory'}],
                 'Customer can only appear once': [GROUP_ROW, {'business_doctype': 'Customer', 'access': 'Record',
                                                               'value': self.ungrouped[0]}]}
        for message, business in cases.items():
            with self.subTest(message=message):
                response = self.post('teams.save', self.manager, name=self.team, title=TEAM, members=[self.AGENT], business=business)
                self.assertEqual(response.status_code, 417)
                self.assertIn(message, response.text)
        read = self.get('teams.read', self.manager, name=self.team).json()['message']
        self.assertEqual(read['business'], [GROUP_ROW], 'A refused save keeps the team as it was')

    def test_a_user_reaches_only_the_records_of_their_teams(self):
        self.assertEqual(self.get('api.business_types', self.agent).json()['message'], ['Customer'])
        names = {row['name'] for row in self.get('api.business_records', self.agent, doctype='Customer').json()['message']}
        self.assertTrue(set(self.grouped) | {self.ungrouped[0]} <= names)
        self.assertNotIn(self.ungrouped[1], names)
        self.assertEqual(self.get('api.business_types', self.outsider).json()['message'], [])
        self.assertEqual(self.get('api.business_records', self.outsider, doctype='Customer').status_code, 403)
        manager = {row['name'] for row in self.get('api.business_records', self.manager, doctype='Customer').json()['message']}
        self.assertIn(self.ungrouped[1], manager)

    def test_record_pages_lists_and_titles_stop_at_the_team_records(self):
        inbox = {row['name'] for row in self.get('business_inbox.records', self.agent, doctype='Customer').json()['message']['items']}
        self.assertIn(self.ungrouped[0], inbox)
        self.assertNotIn(self.ungrouped[1], inbox)
        self.assertEqual(self.get('business_inbox.context', self.agent, doctype='Customer', name=self.ungrouped[0]).status_code, 200)
        self.assertEqual(self.get('business_inbox.context', self.agent, doctype='Customer', name=self.ungrouped[1]).status_code, 403)
        self.assertEqual(self.get('business_inbox.context', self.manager, doctype='Customer', name=self.ungrouped[1]).status_code, 200)
        titles = self.get('display.titles', self.agent, records=json.dumps(
            [{'doctype': 'Customer', 'name': name} for name in self.ungrouped[:2]])).json()['message']['items']
        self.assertEqual([row['name'] for row in titles], [self.ungrouped[0]])

    def test_a_ticket_without_a_chat_needs_a_reachable_record_and_opens_to_mentioned_people(self):
        response = self.ticket(self.agent, self.grouped[0], brief='Please check @Local teams mentioned',
                               mentions=[self.MENTIONED], assigned_to=self.AGENT)
        self.assertEqual(response.status_code, 200, response.text)
        name = response.json()['message']['name']
        self.assertEqual(self.ticket(self.agent, self.ungrouped[1]).status_code, 403)
        self.assertEqual(self.post('tickets.create', self.agent, subject='Relay teams fixture no record').status_code, 417)
        ticket = self.get('tickets.read', self.mentioned, name=name)
        self.assertEqual(ticket.status_code, 200)
        self.assertEqual((ticket.json()['message']['business_name'], ticket.json()['message']['mentions']),
                         (self.grouped[0], [self.MENTIONED]))
        mentions = self.get('tickets.directory', self.mentioned, mentioned=1).json()['message']['items']
        self.assertIn(name, [row['name'] for row in mentions])
        self.assertEqual(self.get('tickets.read', self.outsider, name=name).status_code, 403)
        self.assertNotIn(name, [row['name'] for row in self.get('tickets.directory', self.outsider).json()['message']['items']])
        self.assertIn(name, [row['name'] for row in self.get('tickets.directory', self.agent).json()['message']['items']])
        colleagues = {row['value'] for row in self.get('tickets.colleagues', self.agent, query='Local teams').json()['message']}
        self.assertEqual(colleagues, {self.MANAGER_USER, self.AGENT, self.MENTIONED}, 'Teammates and managers only')
        self.assertEqual(self.get('tickets.colleagues', {}).status_code, 403)
        outside = self.ticket(self.agent, self.grouped[0], mentions=[self.OUTSIDER])
        self.assertEqual(outside.status_code, 403)
        self.assertIn('share a team', outside.text)
        both = self.get('tickets.directory', self.mentioned, mentioned=1, resolved_today=1).json()['message']['items']
        self.assertNotIn(name, [row['name'] for row in both], 'An open ticket is not resolved today')

    def test_mentioned_people_read_and_comment_and_the_assignee_works_the_ticket(self):
        response = self.ticket(self.agent, self.grouped[0], mentions=[self.MENTIONED], assigned_to=self.AGENT)
        self.assertEqual(response.status_code, 200, response.text)
        name = response.json()['message']['name']
        ticket = self.get('tickets.read', self.mentioned, name=name).json()['message']
        self.assertFalse(ticket['can_edit'])
        comment = self.post('ticket_tags.add_comment', self.mentioned, name=name, body='Stock checked')
        self.assertEqual(comment.status_code, 200, comment.text)
        self.assertEqual(comment.json()['message'][-1]['body'], 'Stock checked')
        mention = self.post('ticket_tags.add_comment', self.mentioned, name=name, body='Ask @agent', mentions=[self.AGENT])
        self.assertEqual(mention.status_code, 403)
        statuses = self.get('ticket_settings.read', self.agent).json()['message']['statuses']
        closed = next(row['name'] for row in statuses if row['state'] == 'Closed')
        self.assertEqual(self.post('tickets.update_status', self.mentioned, name=name, status=closed).status_code, 403)
        self.assertEqual(self.post('tickets.close_and_release', self.mentioned, name=name).status_code, 403)
        self.assertEqual(self.post('tickets.update_status', self.agent, name=name, status=closed).status_code, 200)

    def test_a_chat_of_a_contact_without_records_takes_a_picked_record(self):
        message = self.chat[-1][1]
        missing = self.post('tickets.create', self.manager, subject='Relay teams fixture chat', messages=[message])
        self.assertEqual(missing.status_code, 417)
        self.assertIn('no business record. Pick one', missing.text)
        uncovered = self.post('tickets.create', self.agent, subject='Relay teams fixture chat', messages=[message],
                              business_type='Customer', business_record=self.ungrouped[1])
        self.assertIn(uncovered.status_code, (403, 417), uncovered.text)
        created = self.post('tickets.create', self.manager, subject='Relay teams fixture chat', messages=[message],
                            business_type='Customer', business_record=self.ungrouped[0])
        self.assertEqual(created.status_code, 200, created.text)
        ticket = self.get('tickets.read', self.manager, name=created.json()['message']['name']).json()['message']
        self.assertEqual((ticket['business_doctype'], ticket['business_name']), ('Customer', self.ungrouped[0]))

    def test_teams_off_gives_back_every_record_of_the_assigned_types(self):
        connect()
        try:
            frappe.db.set_single_value('Relay Settings', 'enable_teams', 0)
            frappe.db.commit()
        finally:
            frappe.destroy()
        try:
            self.assertEqual(self.get('api.business_types', self.agent).json()['message'], [], 'Type assignment decides again')
        finally:
            connect()
            frappe.db.set_single_value('Relay Settings', 'enable_teams', 1)
            frappe.db.commit(); frappe.destroy()


if __name__ == '__main__':
    unittest.main()
