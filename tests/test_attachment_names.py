"""Uploaded attachments keep the file name the user chose."""
import base64
import unittest
from unittest.mock import Mock, patch

import frappe

from relay_core import attachments


def saved(file_name):
    file = Mock(file_name=file_name)
    file.name = 'FILE-1'
    return file


class SaveAttachmentTests(unittest.TestCase):
    def save(self, stored_name):
        file = saved(stored_name)
        with patch('frappe.utils.file_manager.save_file', return_value=file) as save:
            result = attachments.save_attachment('invoice.pdf', b'pdf', 'MSG-1')
        save.assert_called_once_with('invoice.pdf', b'pdf', 'Relay Message', 'MSG-1', is_private=1)
        return result

    def test_a_suffixed_duplicate_name_is_set_back_to_the_chosen_name(self):
        file = self.save('invoiceb415d3.pdf')
        file.db_set.assert_called_once_with('file_name', 'invoice.pdf', update_modified=False)

    def test_a_name_frappe_kept_is_not_written_again(self):
        self.save('invoice.pdf').db_set.assert_not_called()

    def test_upload_returns_the_chosen_name(self):
        source, channel = frappe._dict(name='MSG-1'), frappe._dict(channel='WhatsApp')
        file = saved('invoiceb415d3.pdf')
        file.db_set.side_effect = lambda field, value, **_: setattr(file, field, value)
        with patch.object(attachments.messaging, 'readable_source', return_value=(source, channel, {})), \
                patch.object(attachments.file_limits, 'get_max_bytes', return_value=1024), \
                patch('frappe.utils.file_manager.save_file', return_value=file):
            result = attachments.upload('MSG-1', 'invoice.pdf', base64.b64encode(b'pdf').decode())
        self.assertEqual(result, {'name': 'FILE-1', 'filename': 'invoice.pdf', 'size': 3})
