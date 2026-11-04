"""AI spend caps: reserve an estimate in Redis before each provider call, then settle it with the actual cost.

Keys carry their period (site month, skill day) and expire after 40 days, so nothing resets them."""
import frappe
from frappe.utils import flt, now_datetime

CAP_REACHED = 'AI spend cap reached'
DEFAULT_MONTHLY_CAP = 50
DEFAULT_DAILY_CAP = 2
KEY_SECONDS = 40 * 86400


def estimate_usd(model, prompt_chars: int, max_tokens: int) -> float:
    """The cost of one call with `prompt_chars` input (4 characters per token) and `max_tokens` output."""
    input_rate, output_rate = rates(model)
    return prompt_chars / 4 * input_rate / 1e6 + max_tokens * output_rate / 1e6


def actual_usd(model, usage: dict | None) -> float:
    """The provider's reported cost, else the token counts at the model rates."""
    usage = usage or {}
    if flt(usage.get('cost')) > 0:
        return flt(usage['cost'])
    input_rate, output_rate = rates(model)
    return flt(usage.get('prompt_tokens')) * input_rate / 1e6 + flt(usage.get('completion_tokens')) * output_rate / 1e6


def rates(model) -> tuple[float, float]:
    input_rate, output_rate = flt(model.get('cost_per_m_input')), flt(model.get('cost_per_m_output'))
    if input_rate <= 0 or output_rate <= 0:
        raise ValueError(f'AI Model {model.get("name")} needs input and output costs per million tokens')
    return input_rate, output_rate


def reserve(skill, estimate: float) -> dict:
    """Add `estimate` to the site's month and, with a `skill`, to its day. Raise before any provider call when a
    total would pass its cap. `skill` needs `name` and `daily_spend_cap_usd`."""
    today = now_datetime()
    caps = [(f'relay-ai-spend:{frappe.local.site}:{today:%Y-%m}', flt(frappe.db.get_single_value(
        'Relay Settings', 'monthly_spend_cap_usd')) or DEFAULT_MONTHLY_CAP)]
    if skill:
        caps.append((f'relay-ai-spend:{skill.name}:{today:%Y-%m-%d}', daily_cap(skill)))
    cache = frappe.cache
    keys = []
    for key, cap in caps:
        key = cache.make_key(key)
        keys.append(key)
        total = flt(cache.incrbyfloat(key, estimate))
        cache.expire(key, KEY_SECONDS)
        if total > cap:
            for added in keys:
                cache.incrbyfloat(added, -estimate)
            raise ValueError(CAP_REACHED)
    return {'keys': keys, 'estimate': estimate, 'charged': estimate}


def daily_cap(skill) -> float:
    return flt(skill.get('daily_spend_cap_usd')) or DEFAULT_DAILY_CAP


def settle(reservation: dict, actual: float) -> None:
    """Replace the reserved estimate with the actual cost."""
    cache = frappe.cache
    for key in reservation['keys']:
        cache.incrbyfloat(key, actual - reservation.get('charged', reservation['estimate']))
    reservation['charged'] = actual


def refund(reservation: dict) -> None:
    """Remove what the reservation charged; a run replays a turn handed to the AI service and charges it then."""
    settle(reservation, 0)
