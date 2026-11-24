"""Files kept on a Relay Message are listed only to users who can list the message."""
import unittest
from unittest.mock import patch

from relay_core import permissions


class MessageFileQueryTests(unittest.TestCase):
    def test_list_shows_relay_message_files_only_of_listable_messages(self):
        with patch.object(permissions, 'message_query', return_value='(visible)'):
            condition = permissions.message_file_query('agent')
        self.assertEqual(condition, "(COALESCE(`tabFile`.attached_to_doctype,'')!='Relay Message' OR `tabFile`.attached_to_name IN "
                                    "(SELECT `tabRelay Message`.name FROM `tabRelay Message` WHERE (visible)))")

    def test_administrator_is_not_limited(self):
        self.assertEqual(permissions.message_file_query('Administrator'), '')


if __name__ == '__main__':
    unittest.main()
