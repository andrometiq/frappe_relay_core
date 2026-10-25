"""Contact edits keep endpoints, routing and message access in step."""
import unittest
from unittest.mock import patch

from relay_core import identity


class ContactNumberTests(unittest.TestCase):
    def test_international_and_national_formats_share_one_identity(self):
        with patch.object(identity, 'default_calling_code', return_value='91'):
            for value in ('+91 98765 43210', '+91-98765-43210', '(+91) 98765.43210', '0091 98765 43210',
                          '919876543210', '098765 43210', '9876543210'):
                with self.subTest(value=value):
                    self.assertEqual(identity.contact_number(value), '919876543210')

    def test_national_numbers_need_a_system_country(self):
        with patch.object(identity, 'default_calling_code', return_value=''):
            self.assertIsNone(identity.contact_number('09876543210'))
            self.assertEqual(identity.contact_number('+44 20 7946 0958'), '442079460958')

    def test_invalid_values_are_not_identities(self):
        for value in ('', None, 'call me', '+0123456789', '+1234', '+1234567890123456'):
            with self.subTest(value=value):
                self.assertIsNone(identity.contact_number(value))


if __name__ == '__main__':
    unittest.main()
