"""Link this site to the Relay Hub with an enrolment token or a setup code; no keys are copied by hand.

The Hub checks that the caller serves the site address: it calls `proof` back with the site's new API key,
and the answer is an HMAC of the pending nonce with the new callback secret."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener

import frappe
from relay_core import test_mode
from relay_core.hub import HubClient, HubError, NoRedirect
from relay_core.onboarding.messages import OnboardingError
from relay_core.permissions import HUB_SERVICE

PENDING = 'relay-enrolment-nonce'
PENDING_SECONDS = 600
CREDENTIAL = re.compile(r'[A-Za-z0-9_-]{20,200}')
ACCOUNT = re.compile(r'[A-Za-z0-9_-]{1,100}')
LOOPBACK = {'127.0.0.1', '::1'}
# The Hub calls the site back (up to 10 s) before it answers; a shorter wait restores the old secret too early.
ENROL_SECONDS = 40


def hub_origin(value):
    """`https://host[:port][/prefix]` without a trailing slash; plain HTTP only on a loopback IP."""
    parsed = urlsplit(value.strip()) if isinstance(value, str) else None
    if not parsed or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise OnboardingError('hub_origin_missing')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in LOOPBACK):
        raise OnboardingError('hub_origin_missing')
    path = parsed.path.rstrip('/')
    if any(part in ('.', '..') for part in path.split('/')) or '%' in path or '//' in path:
        raise OnboardingError('hub_origin_missing')
    return f'{parsed.scheme}://{parsed.netloc}{path}'


def setup_credential(setup_code=''):
    """(Hub origin, credential, source) from a pasted setup code or link, else from site config."""
    pasted = (setup_code or '').strip() if isinstance(setup_code, str) else ''
    if pasted:
        configured = frappe.conf.get('relay_hub_origin')
        origin = configured
        if pasted.startswith(('https://', 'http://')):
            link = urlsplit(pasted)
            pasted = (parse_qs(link.query).get('code') or [''])[0]
            origin = link._replace(path=link.path.rsplit('/enrol', 1)[0], query='', fragment='').geturl()
        if not CREDENTIAL.fullmatch(pasted):
            raise OnboardingError('setup_code_invalid')
        origin = hub_origin(origin or '')
        # The site's API secret goes to this Hub, so a pasted link never moves a site off its configured Hub.
        if configured and origin != hub_origin(configured):
            raise OnboardingError('hub_origin_mismatch')
        return origin, pasted, 'Setup code'
    token = frappe.conf.get('relay_enrolment_token')
    if not token or not frappe.conf.get('relay_hub_origin'):
        raise OnboardingError('setup_code_required')
    if not isinstance(token, str) or not CREDENTIAL.fullmatch(token):
        raise OnboardingError('token_invalid')
    return hub_origin(frappe.conf.get('relay_hub_origin')), token, 'Site config'


def available():
    """Whether this site can link itself without a setup code."""
    return bool(frappe.conf.get('relay_enrolment_token') and frappe.conf.get('relay_hub_origin'))


def site_origin():
    """The public address the Hub calls back, lower case as the Hub stores it.

    A browser request gives it, behind a gateway too; a script or job has only `host_name`."""
    if not getattr(frappe.local, 'request', None) and not frappe.conf.get('host_name'):
        raise OnboardingError('site_address_unknown')
    parsed = urlsplit(frappe.utils.get_url())
    return f'{parsed.scheme}://{parsed.netloc.lower()}'


def service_user():
    """The site's own Hub callback user: Relay Hub Service only, no password, no welcome mail."""
    email = f'relay-hub@{frappe.local.site}'
    if not frappe.db.exists('User', email):
        user = frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'Relay Hub', 'send_welcome_email': 0,
                               'user_type': 'Website User', 'roles': [{'role': HUB_SERVICE}]})
        user.flags.no_welcome_mail = True
        user.insert(ignore_permissions=True)
    return frappe.get_doc('User', email)


def rotate_secret(user):
    """A new API secret for the service user, committed so the Hub's proof call can use it.

    Returns (api_key, api_secret, previous secret or None)."""
    from frappe.utils.password import get_decrypted_password
    previous = get_decrypted_password('User', user.name, 'api_secret', raise_exception=False) if user.api_key else None
    user.api_key = user.api_key or frappe.generate_hash(length=15)
    secret = frappe.generate_hash(length=32)
    user.api_secret = secret
    user.save(ignore_permissions=True)
    frappe.db.commit()
    return user.api_key, secret, previous


def restore_secret(user_name, previous):
    """Put the old API secret back after a failed enrolment, so the working Hub link keeps working."""
    from frappe.utils.password import remove_encrypted_password, set_encrypted_password
    if previous:
        set_encrypted_password('User', user_name, previous, 'api_secret')
    else:
        remove_encrypted_password('User', user_name, 'api_secret')
    frappe.db.commit()


def request_enrolment(origin, credential, body):
    """POST {origin}/api/enrol; the Hub answer, or OnboardingError with the Hub's error code."""
    url = origin + '/api/enrol'
    test_mode.ensure_allowed(url)
    request = Request(url, data=json.dumps(body).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with build_opener(NoRedirect).open(request, timeout=ENROL_SECONDS) as response:
            result = json.loads(response.read(65537)[:65536])
    except HTTPError as exc:
        code = hub_error_code(exc)
        exc.close()
        raise OnboardingError(code) from None
    except (URLError, TimeoutError, OSError, HubError):
        raise OnboardingError('hub_unavailable') from None
    except ValueError:
        raise OnboardingError('hub_response_invalid') from None
    return enrolled(result)


def hub_error_code(exc):
    try:
        code = json.loads(exc.read(8193)[:8192]).get('error', {}).get('code')
    except (ValueError, AttributeError, OSError):
        code = None
    if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,60}', code):
        return code
    return 'rate_limited' if exc.code == 429 else 'hub_unavailable' if exc.code >= 500 else 'invalid_request'


def enrolled(result):
    """The checked 201 body: site_id, mcp_url, hub_token, hub_origin, re_enrolled."""
    if not isinstance(result, dict) or not isinstance(result.get('site_id'), str) or not ACCOUNT.fullmatch(result['site_id']):
        raise OnboardingError('hub_response_invalid')
    token, mcp_url = result.get('hub_token'), result.get('mcp_url')
    try:
        HubClient(mcp_url, token)
        result['hub_origin'] = hub_origin(result.get('hub_origin') or mcp_url.rsplit('/mcp', 1)[0])
    except (ValueError, TypeError, AttributeError, OnboardingError):
        raise OnboardingError('hub_response_invalid') from None
    return result


def connect(setup_code='', reconnect=False):
    """Enrol once per site; a second caller waits for the first and then sees the link.

    Every call, also on an existing link, reads the Hub channels and checks the link again, so Try again re-checks."""
    from relay_core.settings import value
    with frappe.cache.lock(frappe.cache.make_key('relay-enrolment'), timeout=120, blocking_timeout=60):
        if not reconnect and value('relay_hub_url') and value('relay_hub_token') and value('relay_hub_account'):
            result = {'site_id': value('relay_hub_account'), 'mcp_url': value('relay_hub_url'),
                      'hub_token': value('relay_hub_token'), 're_enrolled': False}
        else:
            result = enrol(setup_code)
    from relay_core.channel_sync import sync
    sync()
    check(result)
    return {'connected': True, 'account': result['site_id'], 're_enrolled': bool(result.get('re_enrolled'))}


def enrol(setup_code):
    """One enrolment call; any failure before the Hub answers puts the old API secret back."""
    origin, credential, source = setup_credential(setup_code)
    site = site_origin()
    user = service_user()
    api_key, api_secret, previous = rotate_secret(user)
    callback_secret, nonce = secrets.token_hex(32), secrets.token_hex(32)
    frappe.cache.set_value(PENDING, {'nonce': nonce, 'secret': callback_secret, 'origin': site},
                           expires_in_sec=PENDING_SECONDS)
    try:
        result = request_enrolment(origin, credential, {
            'origin': site, 'site_name': frappe.local.site, 'display_name': display_name(),
            'core_api_key': api_key, 'core_api_secret': api_secret, 'callback_secret': callback_secret,
            'nonce': nonce, 'relay_core_version': version()})
    except Exception:
        restore_secret(user.name, previous)
        raise
    finally:
        frappe.cache.delete_value(PENDING)
    save(result, callback_secret, source)
    return result


def check(result):
    """The existing `account.get` check: the new token names this account and this site."""
    try:
        binding = HubClient(result['mcp_url'], result['hub_token']).call_tool('account.get', {})
    except HubError:
        raise OnboardingError('hub_check_failed') from None
    if binding.get('account') != result['site_id'] or str(binding.get('site', '')).rstrip('/') != site_origin():
        raise OnboardingError('hub_check_failed')


def save(result, callback_secret, source):
    """The Hub has rotated its credentials, so they are saved even if the following check fails."""
    doc = frappe.get_single('Relay Settings')
    doc.update({'hub_url': result['mcp_url'], 'hub_account': result['site_id'], 'hub_token': result['hub_token'],
                'callback_secret': callback_secret, 'hub_origin': result['hub_origin'],
                'enrolled_at': frappe.utils.now_datetime(), 'enrolment_source': source})
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def proof(nonce, challenge):
    """HMAC_SHA256(callback secret, nonce:challenge:origin) for the one pending nonce, used once."""
    if HUB_SERVICE not in frappe.get_roles():
        frappe.throw('Not permitted', frappe.PermissionError)
    pending = frappe.cache.get_value(PENDING)
    valid = all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in (nonce, challenge))
    if not valid or not isinstance(pending, dict) or not hmac.compare_digest(pending.get('nonce', ''), nonce):
        frappe.throw('Unknown enrolment', frappe.PermissionError)
    frappe.cache.delete_value(PENDING)
    message = f"{nonce}:{challenge}:{pending['origin']}".encode()
    return {'proof': hmac.new(pending['secret'].encode(), message, hashlib.sha256).hexdigest()}


def display_name():
    from relay_core.onboarding.details import business_name
    return str(business_name())[:200]


def version():
    import relay_core
    return relay_core.__version__
