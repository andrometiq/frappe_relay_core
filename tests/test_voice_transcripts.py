"""Inbound voice transcription without a database, Hub or speech provider."""
import contextlib
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class VoiceTranscriptTests(unittest.TestCase):
    def setUp(self):
        from frappe import _dict
        self.rows = {'voice': _dict(doctype='Relay Message', name='voice', direction='Incoming', message_type='audio',
                                    content='Voice message', relay_contact='contact', transcript='', transcript_status='',
                                    transcript_details=None)}
        self.provider = _dict(name='Speech', provider='OpenAI', model='fixture-transcribe', enabled=1,
                              get_password=lambda field: 'synthetic-secret')
        self.settings = {'transcription_provider': 'Speech'}
        db = Mock()
        db.get_single_value.side_effect = lambda doctype, field: self.settings.get(field)

        def get_value(doctype, name, fields, as_dict=False, for_update=False):
            row = self.rows[name]
            if as_dict:
                return _dict({field: row.get(field) for field in fields})
            return row.get(fields)
        db.get_value.side_effect = get_value
        db.set_value.side_effect = lambda doctype, name, values, **kwargs: self.rows[name].update(values)
        self.enqueue = Mock()
        self.frappe = types.SimpleNamespace(db=db, enqueue=self.enqueue, ValidationError=type('ValidationError', (Exception,), {}),
            get_doc=lambda doctype, name: self.provider if doctype == 'Relay AI Provider' else _dict(self.rows[name]),
            cache=types.SimpleNamespace(lock=lambda *args, **kwargs: contextlib.nullcontext()),
            session=types.SimpleNamespace(user='Guest'), set_user=Mock(),
            utils=types.SimpleNamespace(now_datetime=lambda: '2026-10-25 23:00:00', add_to_date=lambda *a, **k: '2026-10-25 22:50:00'))
        self.transcribe = Mock(return_value='Please send the invoice')
        self.realtime = Mock()
        stubs = {'frappe': self.frappe,
                 'relay_core.automation.queue': types.SimpleNamespace(after_message_commit=lambda handler: handler),
                 'relay_core.automation.service': types.SimpleNamespace(message_hash=lambda doc: doc.get('content', '') + doc.message_type),
                 'relay_core.automation.multimodal': types.SimpleNamespace(transcribe=self.transcribe),
                 'relay_core.attachments': types.SimpleNamespace(read=lambda name: types.SimpleNamespace(
                     get_data=lambda: b'OggS-audio', mimetype='audio/ogg')),
                 'relay_core.realtime': types.SimpleNamespace(changed=self.realtime)}
        patcher = patch.dict(sys.modules, stubs)
        patcher.start(); self.addCleanup(patcher.stop)
        path = pathlib.Path(__file__).parents[1] / 'relay_core/voice_transcripts.py'
        spec = importlib.util.spec_from_file_location('voice_transcripts_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def receive(self):
        self.module.on_message(self.frappe.get_doc('Relay Message', 'voice'))

    def test_without_provider_the_message_says_unavailable(self):
        self.settings.clear()
        self.receive()
        self.assertEqual(self.rows['voice'].transcript_status, 'Unavailable')
        self.enqueue.assert_not_called()
        self.realtime.assert_called_once()

    def test_received_voice_note_is_queued_once_in_the_background(self):
        self.receive()
        self.assertEqual(self.rows['voice'].transcript_status, 'Pending')
        kwargs = self.enqueue.call_args.kwargs
        self.assertEqual(self.enqueue.call_args.args, ('relay_core.voice_transcripts.process',))
        self.assertEqual((kwargs['message'], kwargs['queue'], kwargs['job_id'], kwargs['deduplicate'], kwargs['enqueue_after_commit']),
                         ('voice', 'long', 'relay-voice-transcript:voice', True, True))
        self.receive()
        self.enqueue.assert_called_once()
        self.transcribe.assert_not_called()

    def test_text_outgoing_and_legacy_messages_are_ignored(self):
        for change in ({'message_type': 'text'}, {'direction': 'Outgoing'}, {'legacy_source': 'old'}):
            self.rows['voice'].update(transcript_status='', direction='Incoming', message_type='audio', legacy_source=None)
            self.rows['voice'].update(change)
            self.receive()
        self.enqueue.assert_not_called()

    def test_process_stores_transcript_and_is_idempotent(self):
        self.receive()
        self.module.process('voice')
        self.module.process('voice')
        row = self.rows['voice']
        self.assertEqual((row.transcript, row.transcript_status), ('Please send the invoice', 'Completed'))
        self.assertEqual(json.loads(row.transcript_details)['model'], 'fixture-transcribe')
        self.transcribe.assert_called_once_with('fixture-transcribe', 'synthetic-secret', b'OggS-audio', 'audio/ogg', allow_in_test_mode=False)
        self.frappe.set_user.assert_called_with('Guest')

    def test_provider_failure_is_recorded_without_secret(self):
        from relay_core.automation.providers import ProviderError
        self.transcribe.side_effect = ProviderError('Transcription could not be completed')
        self.receive(); self.module.process('voice')
        row = self.rows['voice']
        self.assertEqual(row.transcript_status, 'Failed')
        self.assertEqual(json.loads(row.transcript_details), {'reason': 'Transcription could not be completed', 'attempts': 1})
        self.assertNotIn('synthetic-secret', row.transcript_details)

    def test_edit_during_transcription_discards_old_audio_text(self):
        def edited(*args, **kwargs):
            self.rows['voice'].content = 'Message deleted by sender'
            return 'Old words'
        self.transcribe.side_effect = edited
        self.receive(); self.module.process('voice')
        self.assertEqual(self.rows['voice'].transcript, '')

    def test_attempt_limit_stops_retries(self):
        self.receive()
        self.rows['voice'].transcript_details = json.dumps({'attempts': 3})
        self.module.process('voice')
        self.assertEqual(self.rows['voice'].transcript_status, 'Failed')
        self.transcribe.assert_not_called()

    def test_disabled_provider_turns_pending_into_unavailable(self):
        self.receive()
        self.provider.enabled = 0
        self.module.process('voice')
        self.assertEqual(self.rows['voice'].transcript_status, 'Unavailable')
        self.transcribe.assert_not_called()


def setUpModule():
    """These tests cover AI behavior, so the AI features switch is on."""
    from unittest import addModuleCleanup, mock
    switch = mock.patch('relay_core.ai_features.is_enabled', return_value=True)
    switch.start()
    addModuleCleanup(switch.stop)


if __name__ == '__main__':
    unittest.main()
