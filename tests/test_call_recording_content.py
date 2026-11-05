"""Stored call recordings are served byte for byte."""
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from relay_core import call_records

WEBM = bytes.fromhex('1a45dfa3a34286800142f7800142f2800442f380084282847765626d')  # Frappe's windows-1250 fallback decodes these bytes.


class RecordingContentTests(unittest.TestCase):
    def setUp(self):
        self.record = SimpleNamespace(name='RELAY-REC-1', call='RELAY-CALL-1', file='FILE-1', file_size=len(WEBM),
                                      checksum=hashlib.sha256(WEBM).hexdigest())
        self.file = SimpleNamespace(is_private=1, attached_to_doctype='Relay Call Recording', attached_to_name='RELAY-REC-1',
                                    get_content=lambda encodings=None: WEBM if encodings == () else WEBM.decode('windows-1250'))
        docs = {'Relay Call Recording': self.record, 'Relay Call': SimpleNamespace(name='RELAY-CALL-1'), 'File': self.file}

        def reject(message, *args):
            raise ValueError(message)

        fake = SimpleNamespace(get_doc=lambda doctype, name: docs[doctype], throw=reject, PermissionError=PermissionError)
        for fixture in (patch.object(call_records, 'frappe', fake), patch.object(call_records, 'document_name'),
                        patch.object(call_records, 'require_access'), patch.object(call_records, 'readable')):
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_binary_recording_is_read_byte_exact(self):
        self.assertEqual(call_records.recording_content('RELAY-REC-1'), (self.record, WEBM))

    def test_changed_recording_is_refused(self):
        self.record.checksum = hashlib.sha256(b'other').hexdigest()
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            call_records.recording_content('RELAY-REC-1')


if __name__ == '__main__':
    unittest.main()
