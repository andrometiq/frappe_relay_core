"""Customer-facing text for every onboarding error code, in one place."""
import re

NEW_CODE = 'Ask your Relay provider for a new setup code.'

TEXT = {
    'setup_code_required': 'Enter the setup code your Relay provider gave you.',
    'setup_code_invalid': 'This setup code is not valid. Check that you pasted all of it.',
    'hub_origin_missing': 'This setup code has no Relay Hub address. Paste the full setup link.',
    'token_invalid': 'This setup code is not valid. ' + NEW_CODE,
    'token_expired': 'This setup code has expired. ' + NEW_CODE,
    'token_revoked': 'This setup code was withdrawn. ' + NEW_CODE,
    'token_used_up': 'This setup code was already used for another site. ' + NEW_CODE,
    'origin_not_allowed': "This site's address is not allowed by your setup code. " + NEW_CODE,
    'proof_failed': 'Relay Hub could not confirm that it reached this site. Check the site address and try again.',
    'site_unreachable': 'Relay Hub could not reach this site. Check that the site is online at its public address.',
    'invalid_request': 'Relay Hub refused the request. Contact your Relay provider.',
    'rate_limited': 'Too many tries. Wait a few minutes and try again.',
    'hub_unavailable': 'Relay Hub is not available right now. Try again in a few minutes.',
    'hub_response_invalid': 'Relay Hub sent an answer this site cannot use. Contact your Relay provider.',
    'hub_check_failed': 'This site is linked to Relay Hub, but the connection check failed. Select Try again.',
    'hub_not_connected': 'Connect this site to Relay Hub first.',
    'details_missing': 'Enter your business details first.',
    'signup_unavailable': 'WhatsApp signup is not turned on in Relay Hub yet. Contact your Relay provider.',
    'session_not_found': 'This WhatsApp setup was not found. Start again.',
    'launch_url_invalid': 'Relay Hub sent a setup window address this site does not trust. Contact your Relay provider.',
    'code_invalid': 'The Facebook step timed out. Start again.',
    'token_check_failed': 'Facebook did not give Relay access to the WhatsApp account. Start again.',
    'app_not_approved': 'Relay cannot reach this WhatsApp account yet. Contact your Relay provider.',
    'phone_not_found': 'The number you chose was not found in the WhatsApp account. Start again and choose the number.',
    'number_in_use': 'This number is already connected to another Relay site.',
    'register_rate_limited': 'Meta blocked number registration for 72 hours after too many tries. Try again after {time}.',
    'register_failed': 'Meta did not register the number. Try again, or contact your Relay provider.',
    'sync_window_passed': 'Meta allows the chat copy only in the first 24 hours. The number works, but old chats were not copied.',
    'meta_error': 'Facebook stopped the setup: {detail}',
    'cancelled': 'You closed the Facebook window at {step}. Select Continue with Facebook to try again.',
    'expired': 'This setup timed out. Start again.',
}

GENERIC = 'Something went wrong. Try again, or contact your Relay provider.'
DEFAULTS = {'time': '72 hours', 'detail': 'no reason was given', 'step': 'an early step'}
CODE = re.compile(r'[a-z][a-z0-9_]{1,60}')


class OnboardingError(Exception):
    """A setup step failed with a known code; `text(code)` is what the customer reads."""

    def __init__(self, code, **values):
        super().__init__(code)
        self.code, self.values = code, values

    def as_dict(self):
        return error(self.code, **self.values)


def text(code, **values):
    """The message for `code`; unknown codes get the generic text."""
    template = TEXT.get(code) if isinstance(code, str) else None
    if not template:
        return GENERIC
    given = {key: str(value)[:300] for key, value in values.items() if value not in (None, '')}
    return template.format(**{**DEFAULTS, **given})


def error(code, **values):
    """The API shape of an error: {code, message}."""
    code = code if isinstance(code, str) and CODE.fullmatch(code) else 'unknown'
    return {'code': code, 'message': text(code, **values)}
