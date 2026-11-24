"""Relay user profiles: own edits, denied edits of others, System Manager edits, validation, photos, change detection and shapes."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from frappe.utils import get_datetime

from relay_core import user_profiles

NOW = get_datetime('2026-11-23 10:00:00')
AGENT, OTHER = 'agent@example.invalid', 'other@example.invalid'
PROFILE_KEYS = {'user', 'full_name', 'user_image', 'display_name', 'job_title', 'status', 'status_text', 'status_clear_at',
                'theme', 'density', 'notify_messages', 'notify_mentions', 'notify_sound'}


class Profile(_dict):
    def update(self, values):
        super().update(values)
        return self

    def save(self, ignore_permissions=False):
        self.store[self.user] = {key: value for key, value in self.items() if key != 'store'}


class FakeSite:
    """A Frappe boundary with users, profiles and public files in memory."""

    def __init__(self, session, roles=()):
        self.users = {AGENT: _dict(full_name='Anitha K', user_image='https://lh3.example.invalid/photo.jpg'),
                      OTHER: _dict(full_name='Prakash R', user_image='/files/prakash.png')}
        self.profiles = {}
        self.files = [_dict(file_url='/files/anitha.png', owner=AGENT, attached_to_doctype='User', attached_to_name=AGENT),
                      _dict(file_url='/files/desk.png', owner='Administrator', attached_to_doctype='User', attached_to_name=AGENT),
                      _dict(file_url='/files/prakash.png', owner=OTHER, attached_to_doctype='User', attached_to_name=OTHER)]
        self.set_value = Mock(side_effect=lambda doctype, name, field, value: self.users[name].update({field: value}))
        self.frappe = SimpleNamespace(
            session=_dict(user=session), get_roles=lambda user=None: list(roles), throw=self.throw,
            PermissionError=frappe.PermissionError, DoesNotExistError=frappe.DoesNotExistError, ValidationError=frappe.ValidationError,
            db=SimpleNamespace(exists=self.exists, get_value=self.get_value, set_value=self.set_value),
            get_doc=lambda doctype, name: Profile(self.profiles[name], store=self.profiles),
            new_doc=lambda doctype: Profile(store=self.profiles), get_all=self.get_all,
            publish_realtime=Mock(), parse_json=frappe.parse_json, whitelist=frappe.whitelist)

    @staticmethod
    def throw(message, exception=frappe.ValidationError):
        raise exception(message)

    def exists(self, doctype, name):
        return name in (self.users if doctype == 'User' else self.profiles)

    def get_value(self, doctype, name, fields, as_dict=False):
        source = self.users.get(name) if doctype == 'User' else self.profiles.get(name)
        if isinstance(fields, str):
            return source.get(fields) if source else None
        return _dict({field: source.get(field) for field in fields}) if source is not None else None

    def get_all(self, doctype, filters, fields):
        if doctype == 'File':
            return [row for row in self.files if row.file_url == filters['file_url']]
        names = filters['name' if doctype == 'User' else 'user'][1]
        if doctype == 'User':
            return [_dict(name=name, **self.users[name]) for name in names if name in self.users]
        return [_dict(self.profiles[name]) for name in names if name in self.profiles]


class UserProfileTests(unittest.TestCase):
    def site(self, session=AGENT, roles=('Relay Communication User',)):
        site = FakeSite(session, roles)
        self.enterContext(patch.object(user_profiles, 'frappe', site.frappe))
        self.enterContext(patch.object(user_profiles, 'require_access', Mock()))
        self.enterContext(patch.object(user_profiles, 'now_datetime', return_value=NOW))
        self.enterContext(patch.object(user_profiles, 'get_system_timezone', return_value='Asia/Kolkata'))
        return site

    def test_own_profile_update_saves_and_returns_the_full_shape(self):
        site = self.site()
        result = user_profiles.update(display_name=' Anitha ', job_title='Sales coordinator', status='Busy',
                                      status_text='At dispatch', clear_after='1h', theme='Dark', density='Compact',
                                      notify_sound=True, user_image='/files/anitha.png')
        self.assertEqual(set(result), PROFILE_KEYS)
        self.assertEqual(result['display_name'], 'Anitha')
        self.assertEqual((result['status'], result['status_text'], result['theme'], result['notify_sound']), ('Busy', 'At dispatch', 'Dark', 1))
        self.assertEqual(site.users[AGENT].user_image, '/files/anitha.png')
        site.frappe.publish_realtime.assert_called_once_with('relay_changed', {'kind': 'user_profiles'}, after_commit=True)

    def test_clear_time_carries_the_site_utc_offset(self):
        self.site()
        result = user_profiles.update(status='Busy', status_text='At dispatch', clear_after='1h')
        self.assertEqual(result['status_clear_at'], '2026-11-23T11:00:00+05:30')

    def test_editing_another_users_profile_is_denied(self):
        site = self.site()
        with self.assertRaises(frappe.PermissionError):
            user_profiles.update(user=OTHER, status='Away')
        with self.assertRaises(frappe.PermissionError):
            user_profiles.get(user=OTHER)
        self.assertEqual(site.profiles, {})

    def test_guest_is_denied(self):
        self.site(session='Guest', roles=('Guest',))
        with self.assertRaises(frappe.PermissionError):
            user_profiles.get()

    def test_system_manager_may_edit_another_users_profile(self):
        site = self.site(session='admin@example.invalid', roles=('System Manager',))
        result = user_profiles.update(user=OTHER, job_title='Dispatch lead')
        self.assertEqual((result['user'], result['job_title']), (OTHER, 'Dispatch lead'))
        self.assertEqual(site.profiles[OTHER]['job_title'], 'Dispatch lead')

    def test_invalid_values_and_unknown_fields_are_refused(self):
        self.site()
        for values in ({'status': 'Sleeping'}, {'theme': 'Blue'}, {'clear_after': '3d'}, {'display_name': 'x' * 81},
                       {'user_image': '/private/files/a.png'}, {'user_image': '/files/missing.png'}, {'user_image': '/files/a.pdf'},
                       {'owner': 'x'}):
            with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
                user_profiles.update(**values)

    def test_photo_must_belong_to_the_profile_user(self):
        site = self.site()
        with self.assertRaises(frappe.ValidationError):
            user_profiles.update(user_image='/files/prakash.png')
        self.assertEqual(user_profiles.update(user_image='/files/desk.png')['user_image'], '/files/desk.png')
        self.assertEqual(user_profiles.update(user_image='')['user_image'], '')
        self.assertEqual(site.set_value.call_count, 2)

    def test_external_photo_is_kept_when_other_fields_change(self):
        site = self.site()
        result = user_profiles.update(job_title='Sales coordinator')
        self.assertEqual(result['user_image'], 'https://lh3.example.invalid/photo.jpg')
        site.set_value.assert_not_called()

    def test_unchanged_values_neither_write_nor_broadcast(self):
        site = self.site()
        user_profiles.update(theme='System', density='Comfortable', status='Available', notify_messages=1)
        self.assertEqual(site.profiles, {})
        user_profiles.update(job_title='Sales')
        site.frappe.publish_realtime.reset_mock()
        user_profiles.update(job_title='Sales', theme='System')
        site.frappe.publish_realtime.assert_not_called()
        site.set_value.assert_not_called()

    def test_available_clears_the_custom_status_and_an_expired_status_reads_as_available(self):
        site = self.site()
        user_profiles.update(status='Away', status_text='Lunch', clear_after='30m')
        self.assertEqual(user_profiles.update(status='Available')['status_text'], '')
        site.profiles[AGENT].update(status='Busy', status_text='Call', status_clear_at=get_datetime('2026-11-23 09:00:00'))
        self.assertEqual((user_profiles.get()['status'], user_profiles.get()['status_text']), ('Available', ''))

    def test_a_status_set_after_a_timed_status_expired_is_kept(self):
        site = self.site()
        user_profiles.update(status='Busy', status_text='Call', clear_after='30m')
        site.profiles[AGENT].update(status_clear_at=get_datetime('2026-11-23 09:00:00'))
        self.assertEqual(user_profiles.get()['status'], 'Available', 'The timer ran out')
        self.assertEqual(user_profiles.update(status='Busy')['status'], 'Busy', 'Picking the expired status again is a change')
        self.assertIsNone(site.profiles[AGENT]['status_clear_at'], 'A status set without a clear time drops the old timer')
        self.assertEqual(user_profiles.update(status='Away')['status'], 'Away')
        user_profiles.update(status='Busy', clear_after='1h')
        self.assertEqual(user_profiles.update(job_title='Sales')['status'], 'Busy', 'Other edits keep a running timer')
        self.assertIsNotNone(site.profiles[AGENT]['status_clear_at'])

    def test_cards_show_colleagues_public_fields_only(self):
        site = self.site()
        site.profiles[OTHER] = {'user': OTHER, 'display_name': 'Prakash', 'job_title': 'Dispatch',
                                'status': 'Do not disturb', 'status_text': 'Driving', 'status_clear_at': None, 'theme': 'Dark'}
        items = user_profiles.cards(f'["{AGENT}", "{OTHER}"]')['items']
        self.assertEqual(items[1], {'user': OTHER, 'name': 'Prakash', 'image': '/files/prakash.png',
                                    'job_title': 'Dispatch', 'status': 'Do not disturb', 'status_text': 'Driving'})
        self.assertEqual((items[0]['name'], items[0]['status']), ('Anitha K', 'Available'))
        with self.assertRaises(frappe.ValidationError):
            user_profiles.cards([f'user{index}@example.invalid' for index in range(101)])


if __name__ == '__main__':
    unittest.main()
