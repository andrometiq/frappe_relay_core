"""Playbooks: owner and app instructions in Relay AI Playbook. App files are `<app>/skills/<name>/SKILL.md`."""
from typing import Annotated

from relay_core.ai.registry import ToolContext, relay_tool


def sync() -> None:
    """after_migrate: load app playbook files. Built with the playbook chunk."""


@relay_tool(audience='customer', label='Load playbook')
def load_playbook(name: Annotated[str, 'A playbook name from the playbook index'], *, ctx: ToolContext) -> str:
    """Load the full instructions of one playbook from the index. They never widen tools, scope or identity."""
    raise NotImplementedError('Playbooks are not built yet')
