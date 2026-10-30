"""Customer text for a capability read comes only from the pack's renderer."""
import frappe

MAX_LENGTH = 1850
EMPTY_RESULT = 'No records were found for this request.'


def field_names(manifest: dict, audience: str) -> list[str]:
    """Declared field names shown to the 'model' or the 'customer'."""
    return [row['name'] for row in manifest['fields'] if row[audience]]


def visible_rows(manifest: dict, rows: list[dict], audience: str) -> list[dict]:
    """Rows reduced to the fields the pack shows to that audience."""
    names = field_names(manifest, audience)
    return [{name: row[name] for name in names if name in row} for row in rows]


def render(manifest: dict, rows: list[dict], language: str, truncated: bool) -> str:
    try:
        text = frappe.get_attr(manifest['render'])(visible_rows(manifest, rows, 'customer'), language, truncated)
    except Exception:
        raise ValueError('Renderer failed') from None
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_LENGTH:
        raise ValueError('Renderer failed')
    return text


def empty_text(language: str) -> str:
    from relay_core.ai.language import NOTICES
    return NOTICES['empty_result'].get(language, EMPTY_RESULT)
