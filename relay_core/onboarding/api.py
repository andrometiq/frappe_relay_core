"""Get started endpoints. A System Manager sets the site up; managers may read where it stands."""
import functools

import frappe
from relay_core.onboarding import details, enrolment, progress, signup
from relay_core.onboarding.messages import OnboardingError, error
from relay_core.permissions import can_configure, can_manage, require_access


class OnboardingFailed(frappe.ValidationError):
    pass


def system_manager():
    require_access()
    if frappe.session.user != 'Administrator' and 'System Manager' not in frappe.get_roles():
        frappe.throw('Only a System Manager can set up Relay', frappe.PermissionError)


def readable_errors(method):
    """A known setup failure reaches the browser as its customer text."""
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OnboardingError as failure:
            frappe.throw(failure.as_dict()['message'], OnboardingFailed)
    return wrapper


@frappe.whitelist(methods=['GET'])
def state():
    require_access()
    if not (can_configure() or can_manage()):
        frappe.throw('Not permitted', frappe.PermissionError)
    return progress.state()


@frappe.whitelist(methods=['POST'])
def connect_hub(setup_code='', reconnect=0):
    """{connected, account}, or {connected: false, error: {code, message}} with nothing changed."""
    system_manager()
    from redis.exceptions import LockError
    try:
        return enrolment.connect(setup_code, reconnect=str(reconnect) in ('1', 'true', 'True'))
    except OnboardingError as failure:
        return {'connected': progress.is_connected(), 'error': failure.as_dict()}
    except LockError:
        return {'connected': progress.is_connected(), 'error': error('rate_limited')}


@frappe.whitelist(methods=['POST'])
def enrolment_proof(nonce=None, challenge=None):
    return enrolment.proof(nonce, challenge)


@frappe.whitelist(methods=['POST'])
def save_draft(name=None, email=None, website=None, no_website=0, country=None, timezone=None, timezone_name=None,
               display_name=None, category=None, description=None):
    system_manager()
    details.save({'name': name, 'email': email, 'website': website, 'no_website': str(no_website) in ('1', 'true', 'True'),
                  'country': country, 'timezone': timezone, 'timezone_name': timezone_name,
                  'display_name': display_name, 'category': category, 'description': description})
    return {'saved': True}


@frappe.whitelist(methods=['POST'])
@readable_errors
def start_whatsapp(flow):
    system_manager()
    draft = details.saved()
    if not draft:
        raise OnboardingError('details_missing')
    return signup.start(flow, draft)


@frappe.whitelist(methods=['GET'])
@readable_errors
def signup_status(session, refresh=0):
    require_access(configure=True)
    return signup.status(session, refresh=str(refresh) in ('1', 'true', 'True'))


@frappe.whitelist(methods=['POST'])
@readable_errors
def resume_signup(session):
    system_manager()
    return signup.resume(session)


@frappe.whitelist(methods=['POST'])
@readable_errors
def cancel_signup(session):
    system_manager()
    return signup.cancel(session)


@frappe.whitelist(methods=['POST'])
def send_test(channel, to):
    """Meta's `hello_world` template through the normal send path."""
    system_manager()
    from relay_core.messaging_api import send_template
    return send_template(to, 'hello_world', 'en_US', channel=channel)


@frappe.whitelist(methods=['GET'])
def test_status(message):
    system_manager()
    row = frappe.db.get_value('Relay Message', {'name': message, 'direction': 'Outgoing'},
                              ['status', 'delivery_error'], as_dict=True) if isinstance(message, str) else None
    if not row:
        frappe.throw('Test message not found')
    return {'status': row.status, 'error': row.delivery_error or ''}


@frappe.whitelist(methods=['POST'])
def finish():
    system_manager()
    frappe.db.set_single_value('Relay Settings', 'onboarding_completed', 1)
    return {'completed': True}
