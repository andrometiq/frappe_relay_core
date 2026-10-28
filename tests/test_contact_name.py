"""Contact display name validation."""
import unittest
from unittest.mock import patch

from relay_core import contacts


def throw(message, error=ValueError):
    raise error(message)


class DisplayNameTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(contacts.frappe, 'throw', side_effect=throw))

    def reject(self, value, text):
        with self.assertRaises(ValueError) as caught:
            contacts.display_name(value)
        self.assertEqual(str(caught.exception), text)

    def test_valid_name_is_trimmed(self):
        self.assertEqual(contacts.display_name('  Maya Rao '), 'Maya Rao')

    def test_angle_brackets(self):
        self.reject('a<b', 'Name cannot contain < or >')
        self.reject('a>b', 'Name cannot contain < or >')

    def test_tabs_and_line_breaks(self):
        self.reject('a\tb', 'Name cannot contain tabs or line breaks')
        self.reject('a\nb', 'Name cannot contain tabs or line breaks')

    def test_hidden_characters(self):
        for char in ('​', '‏', '‮', '⁦', '⁩'):
            self.reject('a' + char + 'b', 'Name cannot contain hidden or direction-control characters')

    def test_length(self):
        self.reject('x' * 141, 'Enter a name of at most 140 characters')
        self.reject('  ', 'Enter a name of at most 140 characters')
