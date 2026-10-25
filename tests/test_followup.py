"""Regression coverage for automation isolation and lossless message display."""
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core.automation import queue, service
from relay_core.inbox import directory_preview
from relay_core.relay_core.doctype.relay_message.relay_message import RelayMessage
import test_business_routing as routing_tests


class FollowupTests(unittest.TestCase):
    def test_invalid_scope_is_triaged_and_other_messages_continue(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(1,)]
        fake.get_all.side_effect = [['bad-config', 'healthy-channel'], []]
        error = ValueError('Event scope configuration is invalid')
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process', side_effect=[error, None]) as process, \
                patch.object(queue, 'recover'), patch.object(service, 'configuration_failure') as failure:
            self.assertEqual(queue.drain(), 2)
        failure.assert_called_once_with('bad-config', error)
        self.assertEqual([call.args[0] for call in process.call_args_list], ['bad-config', 'healthy-channel'])
        fake.db.rollback.assert_called_once()
        fake.db.set_value.assert_called_once_with('Relay Message', 'bad-config', 'automation_status', 'Complete', update_modified=False)

    def test_configuration_failure_marks_existing_pending_run_once(self):
        fake = Mock(session=_dict(user='operator'))
        fake.db.get_value.return_value = 'run'
        run = _dict(name='run', status='Pending')
        fake.get_doc.side_effect = [_dict(name='message'), run, _dict(name='message'), run]
        contact = _dict(automation_paused=0, automation_generation=2, save=Mock())
        with patch.object(service, 'frappe', fake), patch.object(service, 'internal_save') as save, \
                patch.object(service, 'episode') as episode, patch.object(service, 'lock_contact', return_value=contact):
            service.configuration_failure('message', ValueError('Competing enabled skills'))
            self.assertEqual(run.status, 'Handoff')
            self.assertEqual(run.reason, 'Automation configuration requires review')
            service.configuration_failure('message', ValueError('Replay'))
        save.assert_called_once_with(run)
        self.assertEqual((contact.automation_paused, contact.automation_generation), (0, 2))
        episode.assert_called_once_with(run, unittest.mock.ANY, hold=True)
        contact.save.assert_not_called()

    def test_new_plain_text_preview_preserves_literal_entities_and_markup(self):
        content = 'Quantity 30 Total 1500 Local & team <review> "yes" \'ok\' &amp; literal <script>alert(1)</script>'
        for provider in ('WhatsApp', 'Telegram', 'Email'):
            doc = _dict(content=content, message_type='text', direction='Incoming', provider=provider)
            RelayMessage.before_insert(doc)
            self.assertEqual(json.loads(doc.message_data)['text'], content)
            self.assertEqual(directory_preview(doc), content)
        schema = json.loads(Path('relay_core/relay_core/doctype/relay_message/relay_message.json').read_text())
        self.assertEqual(next(f for f in schema['fields'] if f['fieldname'] == 'content')['ignore_xss_filter'], 1)

    def test_voice_note_preview_includes_its_transcript(self):
        data = json.dumps({'kind': 'audio', 'media': {'id': '1', 'voice': True}})
        self.assertEqual(directory_preview(_dict(message_data=data)), 'Voice message')
        self.assertEqual(directory_preview(_dict(message_data=data, transcript='Send the blue shirts')),
                         'Voice message: Send the blue shirts')

    def test_historical_tokens_use_business_label_in_preview_and_thread(self):
        from relay_core.message_display import decorate_messages
        row = _dict(content='relay-business:'+'a'*32, channel='email', business_doctype='Supplier')
        self.assertEqual(directory_preview(row), 'Chose: Supplier')
        decorate_messages([row], {'email':_dict(channel='Email')})
        self.assertEqual(row.content, 'Chose: Supplier')
        self.assertEqual(row.message_data, {'kind':'text','text':'Chose: Supplier'})


class HumanChoiceTests(routing_tests.RoutingFixtures, unittest.TestCase):
    telegram = routing_tests.ChannelRoutingTests.telegram
    email = routing_tests.ChannelRoutingTests.email
    def test_numeric_answer_and_legacy_token_store_human_text(self):
        for context in (self.telegram(), self.email()):
            for answer in ('2', 'legacy'):
                self.states.clear(); self.actions.clear()
                self.resolve(context=context)
                prompt = next(iter(self.actions.values()))
                self.assertNotIn('relay-business:', prompt.preview)
                self.assertIn('2. Supplier', prompt.preview)
                choice = json.loads(self.state().choices)[1]
                row = {'id': 'choice', 'text': {'body': choice['id'] if answer == 'legacy' else answer}}
                self.assertEqual(__import__('relay_core.business_routing', fromlist=['resolve']).resolve(
                    'contact', 'channel', '15550000001', context, row, _dict(name='choice', creation=self.now)),
                    (self.links[1], 'sender_choice'))
                self.assertTrue(row['message_data']['text'].startswith('Chose: Supplier'))
                self.assertNotIn('relay-business:', row['text']['body'])

    def test_later_numeric_message_is_not_treated_as_another_business_choice(self):
        from relay_core import business_routing
        context = self.telegram()
        self.resolve(context=context)
        row = {'id':'choice', 'text':{'body':'2'}}
        business_routing.resolve('contact','channel','15550000001',context,row,_dict(name='choice',creation=self.now))
        self.now += timedelta(seconds=1)
        row = {'id':'quantity', 'text':{'body':'2'}}
        self.assertEqual(business_routing.resolve('contact','channel','15550000001',context,row,
            _dict(name='quantity',creation=self.now)), (self.links[1], 'conversation'))
        self.assertEqual(row['text']['body'], '2')
