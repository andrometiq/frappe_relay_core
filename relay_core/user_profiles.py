"""Relay user profiles: photo, display name, job title, status and preferences.

A user reads and edits only their own profile; a System Manager may edit anyone's. Colleagues see the public card.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, get_system_timezone, getdate, now_datetime
from relay_core.permissions import require_access

DOCTYPE = 'Relay User Profile'
STATUSES = ('Available', 'Busy', 'Away', 'Do not disturb')
CHOICES = {'status': STATUSES, 'theme': ('System', 'Light', 'Dark'), 'density': ('Comfortable', 'Compact')}
TEXTS = {'display_name': 80, 'job_title': 80, 'status_text': 100}
FLAGS = ('notify_messages', 'notify_mentions', 'notify_sound')
CLEAR_AFTER = {'30m': {'minutes': 30}, '1h': {'hours': 1}, '4h': {'hours': 4}, 'week': {'days': 7}}
DEFAULTS = {'display_name': '', 'job_title': '', 'status': 'Available', 'status_text': '', 'status_clear_at': None,
            'theme': 'System', 'density': 'Comfortable', 'notify_messages': 1, 'notify_mentions': 1, 'notify_sound': 0}
MAX_CARDS = 100
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp')


def target_user(user=None):
    """The profile owner: the session user, or another user for a System Manager."""
    session = frappe.session.user
    user = user or session
    if session == 'Guest' or not isinstance(user, str):
        frappe.throw('Not permitted', frappe.PermissionError)
    if user != session and 'System Manager' not in frappe.get_roles(session):
        frappe.throw('You can edit only your own profile', frappe.PermissionError)
    if not frappe.db.exists('User', user):
        frappe.throw('User not found', frappe.DoesNotExistError)
    return user


def is_expired(clear_at):
    return bool(clear_at) and get_datetime(clear_at) <= now_datetime()


def stored(user):
    values = frappe.db.get_value(DOCTYPE, user, list(DEFAULTS), as_dict=True) or {}
    profile = {key: values.get(key) if values.get(key) is not None else default for key, default in DEFAULTS.items()}
    if is_expired(profile['status_clear_at']):
        profile.update(status='Available', status_text='', status_clear_at=None)
    return profile


def profile_of(user):
    account = frappe.db.get_value('User', user, ['full_name', 'user_image'], as_dict=True)
    profile = stored(user)
    profile['status_clear_at'] = zoned(profile['status_clear_at'])
    for flag in FLAGS:
        profile[flag] = int(profile[flag] or 0)
    return {'user': user, 'full_name': account.full_name or user, 'user_image': account.user_image or '', **profile}


def zoned(value):
    """An ISO time with the site's UTC offset, so every browser shows the same moment."""
    if not value:
        return None
    return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()


@frappe.whitelist(methods=['GET'])
def get(user=None):
    """The full profile with preferences, for its owner or a System Manager."""
    require_access()
    return profile_of(target_user(user))


def clean(values, user):
    """Validated field values from an update request; unknown fields are refused."""
    allowed = set(TEXTS) | set(CHOICES) | set(FLAGS) | {'clear_after', 'user_image'}
    unknown = set(values) - allowed
    if unknown:
        frappe.throw('Unknown profile fields: ' + ', '.join(sorted(unknown)))
    result = {}
    for key, value in values.items():
        if key in TEXTS:
            if value is not None and not isinstance(value, str):
                frappe.throw(f'Invalid {key}')
            value = (value or '').strip()
            if len(value) > TEXTS[key] or any(ord(c) < 32 for c in value):
                frappe.throw(f'{key.replace("_", " ").capitalize()} is too long or has control characters')
        elif key in CHOICES and value not in CHOICES[key]:
            frappe.throw(f'Choose a valid {key}')
        elif key in FLAGS:
            value = 1 if value in (1, True, '1', 'true') else 0
        elif key == 'clear_after':
            value = clear_time(value)
        elif key == 'user_image':
            value = image_url(value, user)
        result[key] = value
    return result


def clear_time(value):
    """When a status clears: empty means never, 'today' means the end of today."""
    if value in (None, ''):
        return None
    if value == 'today':
        return get_datetime(f'{getdate()} 23:59:59')
    if value not in CLEAR_AFTER:
        frappe.throw('Choose a valid time to clear the status')
    return add_to_date(now_datetime().replace(microsecond=0), **CLEAR_AFTER[value])


def image_url(value, user):
    """A public image the user uploaded or attached to their User record, or empty to remove the photo."""
    if value in (None, ''):
        return ''
    if not isinstance(value, str) or not value.startswith('/files/') or not value.lower().endswith(IMAGE_EXTENSIONS):
        frappe.throw('Upload a PNG, JPEG, GIF or WebP photo')
    files = frappe.get_all('File', filters={'file_url': value, 'is_private': 0},
                           fields=['owner', 'attached_to_doctype', 'attached_to_name'])
    if not any(row.owner == user or (row.attached_to_doctype == 'User' and row.attached_to_name == user) for row in files):
        frappe.throw('Upload the photo to your own profile first')
    return value


@frappe.whitelist(methods=['POST'])
def update(user=None, **values):
    """Change the profile fields given; returns the updated profile."""
    require_access()
    user = target_user(user)
    values.pop('cmd', None)
    changes = clean(values, user)
    changed = save_photo(user, changes.pop('user_image')) if 'user_image' in changes else False
    if 'clear_after' in changes:
        changes['status_clear_at'] = changes.pop('clear_after')
    elif 'status' in changes:
        # A status set without a clear time stays until changed; an old timer must not clear it.
        changes['status_clear_at'] = None
    if changes.get('status') == 'Available' and 'status_text' not in changes:
        changes.update(status_text='', status_clear_at=None)
    changed = save_profile(user, changes) or changed
    if changed:
        frappe.publish_realtime('relay_changed', {'kind': 'user_profiles'}, after_commit=True)
    return profile_of(user)


def save_photo(user, image):
    """Write User.user_image only when it changes."""
    if (frappe.db.get_value('User', user, 'user_image') or '') == image:
        return False
    frappe.db.set_value('User', user, 'user_image', image)
    return True


def save_profile(user, changes):
    """Save only the fields that differ from the stored profile; True when something changed."""
    exists = frappe.db.exists(DOCTYPE, user)
    doc = frappe.get_doc(DOCTYPE, user) if exists else frappe.new_doc(DOCTYPE).update({'user': user, **DEFAULTS})
    if is_expired(doc.get('status_clear_at')):
        # An expired status reads as Available, so picking the old status again is a change.
        doc.update({'status': 'Available', 'status_text': '', 'status_clear_at': None})
    changes = {key: value for key, value in changes.items() if not same(doc.get(key), value)}
    if not changes:
        return False
    doc.update(changes)
    doc.save(ignore_permissions=True)
    return True


def same(current, value):
    if isinstance(value, datetime):
        return bool(current) and get_datetime(current) == value
    return str(current if current is not None else '') == str(value if value is not None else '')


@frappe.whitelist(methods=['GET'])
def cards(users):
    """Public cards for colleague avatars: name, photo, job title and status."""
    require_access()
    users = frappe.parse_json(users) if isinstance(users, str) else users
    if not isinstance(users, list) or len(users) > MAX_CARDS or not all(isinstance(user, str) and 0 < len(user) <= 140 for user in users):
        frappe.throw(f'Request at most {MAX_CARDS} users')
    return {'items': user_cards(relay_staff(users))}


def relay_staff(users):
    """The given users who are colleagues: enabled System Users holding a Relay role or System Manager, or members of a
    Relay Team. Website users and other users' names return nothing."""
    from relay_core.permissions import MANAGER, TEAM_USER, USER
    users = [user for user in users if user]
    if not users:
        return []
    staff = set(frappe.get_all('User', filters={'name': ['in', users], 'user_type': 'System User', 'enabled': 1}, pluck='name'))
    if not staff:
        return []
    roles = set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'parent': ['in', list(staff)],
                                                    'role': ['in', [USER, TEAM_USER, MANAGER, 'System Manager']]}, pluck='parent'))
    members = set(frappe.get_all('Relay Team Member', filters={'parenttype': 'Relay Team', 'user': ['in', list(staff - roles)]}, pluck='user')) \
        if staff - roles else set()
    # Administrator holds every role without Has Role rows.
    return [user for user in users if user in (roles | members) or (user == 'Administrator' and user in staff)]


def user_cards(users):
    """Name, photo, job title and status of each user, without an access check; callers check access."""
    accounts = frappe.get_all('User', filters={'name': ['in', users or ['']]}, fields=['name', 'full_name', 'user_image'])
    profiles = {row.user: row for row in frappe.get_all(DOCTYPE, filters={'user': ['in', users or ['']]},
                fields=['user', 'display_name', 'job_title', 'status', 'status_text', 'status_clear_at'])}
    items = []
    for account in accounts:
        profile = profiles.get(account.name) or {}
        expired = is_expired(profile.get('status_clear_at'))
        items.append({'user': account.name, 'name': profile.get('display_name') or account.full_name or account.name,
                      'image': account.user_image or '', 'job_title': profile.get('job_title') or '',
                      'status': 'Available' if expired else profile.get('status') or 'Available',
                      'status_text': '' if expired else profile.get('status_text') or ''})
    return items
