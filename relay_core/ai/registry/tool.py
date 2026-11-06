"""Code tools: `@relay_tool` functions an app lists in its `relay_ai_tools` hook. A tool runs only while an owner
approval matches its exact code hash."""
import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass

import frappe

from relay_core.ai.registry.context import ToolContext
from relay_core.ai.registry.schema import build_schema

AUDIENCES = ('customer', 'staff')
KINDS = ('read', 'action')


@dataclass(frozen=True)
class RelayTool:
    """A tool and its model-facing contract. `action` tools only propose; staff approve through the action journal."""
    name: str
    description: str
    parameters: dict
    function: Callable
    audience: str
    kind: str
    label: str
    business_doctype: str | None = None

    @property
    def code_hash(self) -> str:
        return hashlib.sha256(inspect.getsource(self.function).encode()).hexdigest()

    def __call__(self, arguments: dict, ctx: ToolContext):
        from relay_core.flows.action_contracts import validate
        validate(arguments, self.parameters)
        return self.function(**arguments, ctx=ctx)


def relay_tool(*, audience: str, label: str, kind: str = 'read', business_doctype: str | None = None,
               name: str | None = None) -> Callable[[Callable], RelayTool]:
    """Declare a tool. The docstring is the model description; `ctx` must be keyword-only."""
    if audience not in AUDIENCES or kind not in KINDS or not isinstance(label, str) or not 1 <= len(label) <= 140:
        raise ValueError('A tool needs a customer or staff audience, a read or action kind and a label')

    def wrap(function: Callable) -> RelayTool:
        context = inspect.signature(function).parameters.get('ctx')
        if not context or context.kind is not context.KEYWORD_ONLY:
            raise TypeError(f'Tool {function.__name__} must take `*, ctx: ToolContext`')
        description = inspect.getdoc(function) or ''
        if not 1 <= len(description) <= 1024:
            raise ValueError(f'Tool {function.__name__} needs a docstring of at most 1024 characters')
        return RelayTool(name=name or function.__name__, description=description, parameters=build_schema(function),
                         function=function, audience=audience, kind=kind, label=label,
                         business_doctype=business_doctype)
    return wrap


def offered(skill, audience: str = 'customer') -> list[tuple[str, RelayTool]]:
    """(key, tool) for the approved code tools the skill selects that may run for this audience."""
    keys = [row.get('capability') for row in json.loads(skill.get('allowed_tools') or '[]') if isinstance(row, dict)]
    found = []
    for key in keys:
        try:
            found.append((key, load(key, skill, audience)))
        except ValueError:
            continue
    return found


def call(key: str, arguments: dict, ctx: ToolContext, audience: str = 'customer'):
    """Run one offered tool; the approval, audience and code hash are checked again at call time."""
    return load(key, ctx.skill, audience)(arguments, ctx)


def load(key: str, skill, audience: str) -> RelayTool:
    from relay_core.ai.capabilities import active
    manifest = active(key)
    if manifest.get('kind') != 'tool':
        raise ValueError('Capability is not a code tool')
    if manifest['audience'] != audience:
        raise ValueError('Tool is for another audience')
    if manifest.get('business_doctype') not in (None, skill.business_doctype):
        raise ValueError('Tool is outside the skill business type')
    try:
        tool = frappe.get_attr(manifest['path'])
    except (ImportError, AttributeError):
        raise ValueError('Tool is not installed') from None
    if not isinstance(tool, RelayTool) or tool.code_hash != manifest['code_hash']:
        raise ValueError('Tool code changed after approval')
    return tool
