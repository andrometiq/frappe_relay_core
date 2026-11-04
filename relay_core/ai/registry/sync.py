"""Tool manifests from the `relay_ai_tools` hook. `capabilities.sync` stores them as Relay AI Capability rows of
kind Tool, so one loader owns approval status for packs and tools."""
import re

import frappe

from relay_core.ai.registry.tool import RelayTool

HOOK = 'relay_ai_tools'
VERSION = 1


def manifests() -> dict[str, dict]:
    """Every installed app's tools by key. A tool that fails to import is logged and skipped; it then shows as
    Missing. A hook path of another app or a key declared twice fails the whole load."""
    from relay_core.ai.capabilities import KEY
    loaded = {}
    for app in frappe.get_installed_apps():
        for path in frappe.get_hooks(HOOK, app_name=app):
            if not path.startswith(app + '.'):
                raise ValueError(f'{app} must declare tools from its own module')
            try:
                tool = frappe.get_attr(path)
            except Exception:
                frappe.log_error(title=f'Relay AI tool {path} did not load')
                continue
            if not isinstance(tool, RelayTool):
                raise ValueError(f'{path} is not a @relay_tool function')
            key = tool_key(app, tool)
            if not re.fullmatch(KEY, key):
                raise ValueError(f'Tool {key} must be named <prefix>.<lowercase name>')
            if key in loaded:
                raise ValueError(f'Tool {key} is declared twice')
            loaded[key] = manifest(tool, key, app, path)
    return loaded


def tool_key(app: str, tool: RelayTool) -> str:
    """The capability key of an app's tool: the app's capability prefix and the tool name."""
    prefix = (frappe.get_hooks('relay_ai_capability_prefix', app_name=app) or [app])[-1]
    return f'{prefix}.{tool.name}'


def manifest(tool: RelayTool, key: str, app: str, path: str) -> dict:
    """What an owner approves: the model contract and the exact code."""
    return dict(key=key, app=app, kind='tool', version=VERSION, label=tool.label, path=path,
                tool_kind=tool.kind, audience=tool.audience, business_doctype=tool.business_doctype,
                description=tool.description, parameters=tool.parameters, code_hash=tool.code_hash)
