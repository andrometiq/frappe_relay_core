"""Fact memory in Relay AI Memory: short facts per skill or per business, next to the Relay Memory timeline."""
from typing import Annotated

from relay_core.ai.registry import ToolContext, relay_tool


@relay_tool(audience='customer', label='Remember')
def remember(content: Annotated[str, 'One short fact, at most 300 characters'],
             memory_id: Annotated[str | None, 'A saved fact to revise'] = None, *, ctx: ToolContext) -> dict:
    """Save one short fact about the sender's own business for later replies. Every contact of that business
    shares it. Revise an existing fact with memory_id when the limit is reached."""
    raise NotImplementedError('Fact memory is not built yet')


def memory_block(skill, business: tuple[str, str], query: str) -> list[str]:
    """The recalled facts of a reply prompt, most relevant first, as `[id] (shared|own) content`."""
    raise NotImplementedError('Fact memory is not built yet')


def purge_pending() -> None:
    """Daily job: delete customer-written facts still Pending after a day. Built with the fact memory chunk."""
