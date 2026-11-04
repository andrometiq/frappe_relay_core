"""Channel setup endpoints. A System Manager configures; communication managers may read where things stand."""
import frappe
from relay_core.channel_setup import whatsapp
from relay_core.onboarding.api import system_manager
from relay_core.permissions import can_configure, can_manage, require_access

PROVIDERS = {'WhatsApp': whatsapp}


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


@frappe.whitelist(methods=['POST'])
def check_number(channel, repair=1):
    system_manager()
    return whatsapp.check(channel, flag(repair))


@frappe.whitelist(methods=['POST'])
def save_number_settings(channel, settings):
    system_manager()
    return whatsapp.save_settings(channel, frappe.parse_json(settings) if isinstance(settings, str) else settings)


@frappe.whitelist(methods=['POST'])
def set_default(channel):
    system_manager()
    return whatsapp.set_default(channel)


@frappe.whitelist(methods=['POST'])
def reset_pin(channel):
    system_manager()
    return whatsapp.reset_pin(channel)


@frappe.whitelist(methods=['POST'])
def remove_number(channel, confirm=0):
    system_manager()
    return whatsapp.remove(channel, flag(confirm))


@frappe.whitelist(methods=['GET'])
def number_profile(channel):
    readers()
    return whatsapp.profile(channel)


@frappe.whitelist(methods=['POST'])
def save_number_profile(channel, profile, photo_base64='', photo_type=''):
    system_manager()
    values = frappe.parse_json(profile) if isinstance(profile, str) else profile
    return whatsapp.save_profile(channel, values, photo_base64, photo_type)
