"""Personal chat folders stay private to their user."""
import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict
from relay_core import chat_folders
from test_contact_primary import fake_frappe


class ChatFolderTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.session.user = 'agent@example.invalid'
        self.fake.db.escape = lambda value: "'" + value + "'"
        self.owners = {'F-MINE': 'agent@example.invalid', 'F-OTHER': 'other@example.invalid'}
        self.fake.db.get_value.side_effect = lambda doctype, name, field: self.owners.get(name)
        self.fake.db.exists.return_value = False
        self.enterContext(patch.object(chat_folders, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(chat_folders, 'require_access'))

    def folder(self, **values):
        return _dict(user='agent@example.invalid', owner='agent@example.invalid', name='F-MINE', folder_name='Follow up', **values)

    def test_names_are_trimmed_and_bounded(self):
        self.assertEqual(chat_folders.clean_folder_name('  Follow up '), 'Follow up')
        for bad in ('', '   ', 'x' * 51, 'a\nb', None, 5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                chat_folders.clean_folder_name(bad)

    def test_validate_denies_a_folder_for_another_user(self):
        chat_folders.validate_folder(self.folder())
        for field in ('user', 'owner'):
            doc = self.folder()
            doc[field] = 'other@example.invalid'
            with self.assertRaises(PermissionError):
                chat_folders.validate_folder(doc)

    def test_validate_rejects_a_duplicate_name_for_the_same_user(self):
        self.fake.db.exists.return_value = True
        with self.assertRaisesRegex(ValueError, 'already have a folder'):
            chat_folders.validate_folder(self.folder())
        filters = self.fake.db.exists.call_args.args[1]
        self.assertEqual((filters['user'], filters['name']), ('agent@example.invalid', ['!=', 'F-MINE']))

    def test_another_users_folder_is_not_found(self):
        self.assertIs(chat_folders.own_folder('F-MINE'), self.fake.get_doc.return_value)
        for folder in ('F-OTHER', 'F-MISSING', None, 'x' * 141):
            with self.assertRaises(LookupError, msg=repr(folder)):
                chat_folders.own_folder(folder)

    def test_rename_and_delete_deny_another_users_folder_without_writing(self):
        with self.assertRaises(LookupError):
            chat_folders.rename('F-OTHER', 'Mine now')
        with self.assertRaises(LookupError):
            chat_folders.delete('F-OTHER')
        self.fake.get_doc.assert_not_called()
        self.fake.qb.update.assert_not_called()

    def test_delete_clears_only_my_conversations_then_removes_the_folder(self):
        doc = self.fake.get_doc.return_value
        doc.name = 'F-MINE'
        self.assertEqual(chat_folders.delete('F-MINE'), {'name': 'F-MINE'})
        self.fake.qb.update.return_value.set.return_value.where.return_value.run.assert_called_once()
        doc.delete.assert_called_once()

    def test_permission_hooks_scope_to_the_user(self):
        self.assertTrue(chat_folders.permission(_dict(user='agent@example.invalid')))
        self.assertFalse(chat_folders.permission(_dict(user='other@example.invalid')))
        self.assertTrue(chat_folders.permission(_dict(user='other@example.invalid'), user='Administrator'))
        self.assertEqual(chat_folders.query(), "`tabRelay Chat Folder`.user='agent@example.invalid'")
        self.assertEqual(chat_folders.query('Administrator'), '')

    def test_folders_lists_mine_with_counts(self):
        self.fake.qb.from_.return_value.select.return_value.where.return_value.groupby.return_value.run.return_value = [('F-MINE', 4)]
        self.fake.get_all.return_value = [_dict(name='F-MINE', folder_name='Follow up', sort_order=1),
                                          _dict(name='F-EMPTY', folder_name='Later', sort_order=2)]
        self.assertEqual([(row['name'], row['count']) for row in chat_folders.folders()], [('F-MINE', 4), ('F-EMPTY', 0)])
        self.assertEqual(self.fake.get_all.call_args.kwargs['filters'], {'user': 'agent@example.invalid'})

    def test_every_api_requires_relay_access(self):
        self.access.side_effect = PermissionError
        for call in (chat_folders.folders, lambda: chat_folders.create('A'), lambda: chat_folders.rename('F-MINE', 'B'),
                     lambda: chat_folders.delete('F-MINE')):
            with self.assertRaises(PermissionError):
                call()


if __name__ == '__main__':
    unittest.main()
