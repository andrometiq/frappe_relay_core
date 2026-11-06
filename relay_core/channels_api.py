"""Channel setup endpoints. A System Manager configures; communication managers may read where things stand."""
import frappe
from frappe.utils.logger import sanitized_dict
from relay_core.channel_setup import SECRET_FIELDS, email, provider_of, telegram, whatsapp
from relay_core.onboarding.api import system_manager
from relay_core.permissions import can_configure, can_manage, require_access

PROVIDERS = {'WhatsApp': whatsapp, 'Telegram': telegram, 'Email': email}


def provider(name):
    if name not in PROVIDERS:
        frappe.throw(f'{name} accounts are not set up from Relay yet')
    return PROVIDERS[name]


def readers():
    require_access()
    if not (can_configure() or can_manage()):
        frappe.throw('Not permitted', frappe.PermissionError)


def flag(value):
    return str(value) in ('1', 'true', 'True')


@frappe.whitelist(methods=['GET'])
def accounts(channel='WhatsApp'):
    readers()
    return {'accounts': provider(channel).accounts(), 'can_configure': can_configure()}


def owner(channel):
    """The setup module of the provider of one Relay Channel."""
    return provider(provider_of(channel))


def parsed(name, values):
    """The JSON form value `name`. An Error Log records the request form, so its tokens and passwords are masked there."""
    try:
        values = frappe.parse_json(values) if isinstance(values, str) else values
    except ValueError:
        values = None
    form = getattr(frappe.local, 'form_dict', None)
    if isinstance(form, dict) and name in form:
        form[name] = sanitized_dict(values) if isinstance(values, dict) else '********'
    return values


def with_secrets(values, secrets):
    """values with the tokens and passwords that a page sends apart in `secrets`. Frappe masks a field of that name in
    the local variables of a traceback, where a token inside `values` would show. Older pages send them in values."""
    secrets = parsed('secrets', secrets)
    if not isinstance(values, dict) or not isinstance(secrets, dict):
        return values
    return {**values, **{name: secrets[name] for name in SECRET_FIELDS if name in secrets}}


@frappe.whitelist(methods=['POST'])
def connect(channel, values, secrets=None):
    """Connect a bot or mailbox of one provider. The token or password goes to the Hub only."""
    values = with_secrets(parsed('values', values), secrets)
    system_manager()
    module = provider(channel)
    if not hasattr(module, 'connect') or not isinstance(values, dict):
        frappe.throw(f'{channel} accounts are connected from the setup page')
    return module.connect(values)


@frappe.whitelist(methods=['POST'])
def check(channel, repair=1):
    system_manager()
    return owner(channel).check(channel, flag(repair))


@frappe.whitelist(methods=['POST'])
def save_settings(channel, settings, secrets=None):
    settings = with_secrets(parsed('settings', settings), secrets)
    system_manager()
    return owner(channel).save_settings(channel, settings)


@frappe.whitelist(methods=['POST'])
def set_default(channel):
    system_manager()
    return owner(channel).set_default(channel)


@frappe.whitelist(methods=['POST'])
def remove(channel, confirm=0):
    system_manager()
    return owner(channel).remove(channel, flag(confirm))


# The WhatsApp names stay for pages and scripts that still call them.
@frappe.whitelist(methods=['POST'])
def check_number(channel, repair=1):
    return check(channel, repair)


@frappe.whitelist(methods=['POST'])
def save_number_settings(channel, settings):
    return save_settings(channel, settings)


@frappe.whitelist(methods=['POST'])
def reset_pin(channel):
    system_manager()
    return whatsapp.reset_pin(channel)


@frappe.whitelist(methods=['POST'])
def remove_number(channel, confirm=0):
    return remove(channel, confirm)


@frappe.whitelist(methods=['GET'])
def number_profile(channel):
    readers()
    return whatsapp.profile(channel)


@frappe.whitelist(methods=['POST'])
def save_number_profile(channel, profile, photo_base64='', photo_type=''):
    system_manager()
    return whatsapp.save_profile(channel, parsed('profile', profile), photo_base64, photo_type)
