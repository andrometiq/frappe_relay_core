"""Built-in model tools. SEARCH reads one declared report after its declaration; EXECUTE proposes declared actions
in order. Knowledge, playbook and memory tools add their reply guard inputs here."""
from relay_core.ai.playbooks import copy_texts
from relay_core.ai.render import field_names
from relay_core.ai.tools import PrivacyDenied, check_identity_arguments, own_record_arguments
from relay_core.automation.contracts import validate_search


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
        self.knowledge = list(copy_texts(skill, business, (scope or {}).get('company')))
        if skill.get('allowed_actions') and skill.get('allowed_actions') != '[]':
            from relay_core.ai.configuration import action_contracts
            from relay_core.flows.actions import definitions
            self.declarations = action_contracts(skill)
            self.registered = definitions(context='ai')
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
