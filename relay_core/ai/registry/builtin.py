"""Built-in model tools. SEARCH reads one declared report after its declaration; EXECUTE proposes declared actions
in order. Knowledge, playbook and memory tools and approved app read tools run with a trusted ToolContext, and their
results fill the reply guard inputs here."""
import hashlib
import json
import time
from dataclasses import dataclass, field

import frappe

from relay_core.ai.fact_memory import is_available, remember
from relay_core.ai.knowledge_base import retriever
from relay_core.ai.playbooks import copy_texts, load_playbook
from relay_core.ai.registry.context import ToolContext
from relay_core.ai.registry.tool import RelayTool
from relay_core.ai.render import field_names
from relay_core.ai.tools import PrivacyDenied, check_identity_arguments, own_record_arguments
from relay_core.automation.contracts import validate_search

UNAVAILABLE = 'This tool is unavailable'
BUILTINS = (retriever.search_knowledge, load_playbook, remember)


@dataclass
class RunRecord:
    """What the tools of one decision did, for the Automation Run. It holds no row data."""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)

    def add_call(self, name: str, arguments, result: str, started: float) -> None:
        digest = hashlib.sha256(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()
        self.tool_calls.append({'name': name, 'arguments_sha256': digest,
                                'status': 'error' if result.startswith('{"error"') else 'ok',
                                'ms': round((time.monotonic() - started) * 1000)})

    def add_usage(self, outcome: dict, turns: int) -> None:
        """Token usage of an attempt's final turn, which is all the engine reports, and the turns it took."""
        usage = (outcome.get('result') or {}).get('usage') or {} if outcome.get('ok') else {}
        self.usage['turns'] = self.usage.get('turns', 0) + turns
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            self.usage[key] = self.usage.get(key, 0) + int(usage.get(key) or 0)


def is_builtin(tool: RelayTool, *names: RelayTool) -> bool:
    """Whether `tool` is one of `names`, or of all built-in tools when none are named."""
    return any(tool.function is item.function for item in names or BUILTINS)


def skill_tools(skill) -> list[tuple[str, RelayTool]]:
    """(key, tool) of each approved code tool a customer run of the skill may offer: the built-ins its settings ask
    for (knowledge bases, playbooks, customer memory), then the read tools selected in `allowed_tools`. Action tools
    are not offered until they propose through the action journal."""
    from relay_core.ai.registry.sync import tool_key
    from relay_core.ai.registry.tool import load, offered
    wanted = (retriever.bound_bases(skill), skill.get('playbooks'), skill.get('memory_enabled'))
    found = []
    for tool in (tool for tool, is_wanted in zip(BUILTINS, wanted) if is_wanted):
        try:
            found.append((tool_key('relay_core', tool), load(tool_key('relay_core', tool), skill, 'customer')))
        except ValueError:
            continue
    return found + [(key, tool) for key, tool in offered(skill) if tool.kind == 'read' and not is_builtin(tool)]


def tool_hashes(skill) -> dict[str, str]:
    """{key: code hash} of the skill's code tools, so a tool change between decision and delivery stops the reply."""
    return {key: tool.code_hash for key, tool in skill_tools(skill)}


class CoreTools:
    """The per-run state of SEARCH and EXECUTE. `search` is the authorized plan of a confirmed turn, or None."""

    def __init__(self, skill, business, scope, reader, references, minimiser, search):
        self.skill, self.business, self.scope, self.reader = skill, business, scope, reader
        self.references, self.minimiser, self.authorized = references, minimiser, search
        self.proposed, self.read_results, self.actions = [], [], []
        self.declarations, self.action_schemas, self.registered = [], [], {}
        # Reply guard slots: `evidence` allows contact values (returned knowledge chunks, staff memory);
        # `knowledge` texts join the verbatim-copy check (bound playbooks, skill memory).
        self.evidence = []
        self.playbook_texts = copy_texts(skill, business, (scope or {}).get('company'))
        self.knowledge = list(self.playbook_texts)
        self.code_tools, self.context = [], None
        if skill.get('allowed_actions') and skill.get('allowed_actions') != '[]':
            from relay_core.ai.configuration import action_contracts
            from relay_core.flows.actions import definitions, offered_actions
            self.registered = definitions(context='ai')
            self.declarations = offered_actions(action_contracts(skill), self.registered)
            self.action_schemas = [dict(row, parameters=self.registered[row['action']]['parameters'],
                approval_policy=self.registered[row['action']]['approval_policy']) for row in self.declarations]

    def execute(self, action, parameters):
        from relay_core.flows.actions import proposal
        try:
            if self.proposed:
                raise ValueError('Complete the declared search before execution')
            if len(self.actions) >= len(self.declarations) or action != self.declarations[len(self.actions)]['action']:
                raise ValueError('Action differs from the declared sequence')
            self.actions.append(proposal(self.skill, action, self.minimiser.unmask(parameters)))
            return {'status': 'Proposed', 'step': len(self.actions)}
        except Exception:
            self.reader.failed = True
            raise ValueError('Action is unavailable') from None

    def search(self, purpose, reference, arguments):
        purpose, arguments = self.minimiser.unmask([purpose, arguments])
        try:
            contract = next(row for row in self.references if row['key'] == reference)
            arguments = own_record_arguments(contract, arguments, self.business)
            check_identity_arguments(contract, arguments, self.business, self.scope)
            plan = validate_search(dict(purpose=purpose, reference=reference,
                fields=field_names(contract, 'model'), arguments=arguments), self.references)
            if self.authorized is None:
                if self.proposed and self.proposed[0] != plan:
                    raise ValueError('Only one declared search per turn')
                self.proposed[:] = [plan]
                return {'status': 'Declaration required', 'search': plan}
            if plan['purpose'] != self.authorized['purpose']:
                raise ValueError('Search purpose changed after declaration')
            result = self.reader.read(contract, **arguments)
            self.read_results.append(result)
            return self.minimiser.mask(result)
        except PrivacyDenied:
            self.reader.private = True
            raise ValueError('This search is private') from None
        except Exception:
            self.reader.failed = True
            raise ValueError('Search is unavailable') from None

    def agent_tools(self, agent) -> list:
        """SEARCH when the skill has reports for this business, EXECUTE when it declares actions."""
        tools = [agent.Tool('SEARCH', 'Declare a search before reading. Only the authorized exact plan may read.',
            {'type': 'object', 'additionalProperties': False, 'required': ['purpose', 'reference', 'arguments'],
             'properties': {'purpose': {'type': 'string', 'maxLength': 300},
                            'reference': {'type': 'string', 'enum': [r['key'] for r in self.references]},
                            'arguments': {'type': 'object'}}}, self.search)] if self.references else []
        if self.declarations:
            tools.append(agent.Tool('EXECUTE', 'Propose an allowed action in event order. Core executes after validating the complete turn.',
                {'type': 'object', 'additionalProperties': False, 'required': ['action', 'parameters'],
                 'properties': {'action': {'type': 'string', 'enum': [row['action'] for row in self.declarations]},
                                'parameters': {'type': 'object'}}}, self.execute))
        return tools

    def add_code_tools(self, agent, context: ToolContext) -> list:
        """Agent tools for the code tools this run can use; the model never sees `context`."""
        self.context = context
        usable = ((retriever.search_knowledge, lambda: retriever.is_offered(self.skill)),
                  (load_playbook, lambda: bool(self.playbook_texts)),
                  (remember, lambda: bool(context.run) and is_available(self.skill, self.business)))
        self.code_tools = [(key, tool) for key, tool in skill_tools(self.skill)
                           if all(check() for item, check in usable if is_builtin(tool, item))]
        names = [tool.name for key, tool in self.code_tools]
        if len(set(names)) != len(names) or {'SEARCH', 'EXECUTE'} & set(names):
            raise ValueError('Two AI tools share a name')
        return [agent.Tool(tool.name, retriever.description(self.skill)
                           if is_builtin(tool, retriever.search_knowledge) else tool.description, tool.parameters,
                           self.runner(key, tool))
                for key, tool in self.code_tools]

    def runner(self, key: str, tool: RelayTool):
        # Model arguments arrive as keywords, so the key and tool must not be keyword defaults it could override.
        return lambda **arguments: self.call(key, tool, arguments)

    def call(self, key: str, tool: RelayTool, arguments: dict):
        """Run one code tool. Built-in tools give their fixed error texts; app tool errors never reach the model."""
        from relay_core.ai.registry.tool import call
        if self.actions:
            raise ValueError('Call tools before EXECUTE')
        try:
            result = call(key, self.minimiser.unmask(arguments), self.context)
        except ValueError as error:
            raise ValueError(str(error) if is_builtin(tool) else UNAVAILABLE) from None
        except Exception:
            frappe.log_error(title=f'Relay AI tool {key} failed')
            raise ValueError(UNAVAILABLE) from None
        if is_builtin(tool, retriever.search_knowledge):
            self.evidence.append(result)  # Chunks allow contact values only, never names or copied text.
        elif not is_builtin(tool):
            self.read_results.append(result)
        return self.minimiser.mask(result)
