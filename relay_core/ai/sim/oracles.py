"""Expected customer text computed from the seed: `(seed, scenario) -> str`, rendered by the pack's own renderer."""
from relay_core.ai.sim import personas


def language(scenario: dict) -> str:
    return personas.SCRIPTS[scenario['language']]


def business(seed: dict, scenario: dict) -> list[str]:
    return seed['personas'][scenario['persona']]['business']


def rendered(scenario: dict, key: str, rows: list[dict], truncated: bool = False) -> str:
    from relay_core.ai.capabilities import active
    from relay_core.ai.render import empty_text, render
    if not rows:
        return empty_text(language(scenario))
    return render(active(key), rows, language(scenario), truncated)


def records(seed: dict, suite: str, key: str, name: str) -> list[dict]:
    """Rows an adapter seed returned for one business, in the pack's order_by order."""
    return seed['suites'][suite]['records'][key].get(name, [])


def latest_order_line(seed: dict, scenario: dict) -> str:
    key = 'yrp.customer_orders'
    return rendered(scenario, key, records(seed, 'distributor', key, business(seed, scenario)[1])[:1])


def latest_slip_line(seed: dict, scenario: dict) -> str:
    key = 'yrp.customer_slips'
    return rendered(scenario, key, records(seed, 'distributor', key, business(seed, scenario)[1])[:1])


def distributor_october_ledger(seed: dict, scenario: dict) -> str:
    key = 'yrp.customer_ledger'
    return rendered(scenario, key, october(seed['suites']['erpnext']['ledgers'][business(seed, scenario)[1]]))


def october_ledger(seed: dict, scenario: dict) -> str:
    return rendered(scenario, 'erpnext.customer_ledger', october(seed['suites']['erpnext']['ledgers'][business(seed, scenario)[1]]))


def member_profile(seed: dict, scenario: dict) -> str:
    key = 'sihma.member_profile'
    return rendered(scenario, key, records(seed, 'association', key, business(seed, scenario)[1]))


def october(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row['posting_date']).startswith('2026-10')]


def empty_result(seed: dict, scenario: dict) -> str:
    from relay_core.ai.render import empty_text
    return empty_text(language(scenario))


def notice(kind: str, fallback: str, scenario: dict) -> str:
    from relay_core.ai.language import NOTICES
    return NOTICES[kind].get(language(scenario), fallback)


def disclosure_text(seed: dict, scenario: dict) -> str:
    from relay_core.ai.disclosure import DISCLOSURE
    return notice('disclosure', DISCLOSURE, scenario)


def decline_text(seed: dict, scenario: dict) -> str:
    from relay_core.ai.adapter import PRIVACY_REPLY
    return notice('decline', PRIVACY_REPLY, scenario)


def handoff_text(seed: dict, scenario: dict) -> str:
    from relay_core.ai.handoff import ACKNOWLEDGEMENT
    return notice('handoff', ACKNOWLEDGEMENT, scenario)


def approval_notice_text(seed: dict, scenario: dict) -> str:
    from relay_core.ai.service import APPROVAL_NOTICE
    return notice('approval_notice', APPROVAL_NOTICE, scenario)
