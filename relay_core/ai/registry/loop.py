"""The bounded tool loop of a customer reply on frappe_tools' AgentRun."""
import time

from frappe_tools.ai import agent

DEFAULT_TOOL_CALLS = 4
MAX_TOOL_CALLS = 6  # The hard cap for customer channels.
MAX_RESULT_CHARS = 4000
EXPECTED = {'SEARCH': {'purpose', 'reference', 'arguments'}, 'EXECUTE': {'action', 'parameters'}}


def tool_limit(skill) -> int:
    """The skill's model tool calls per reply, never over the hard cap."""
    return min(int(skill.get('max_tool_calls') or DEFAULT_TOOL_CALLS), MAX_TOOL_CALLS)


class SkillRun(agent.AgentRun):
    """AgentRun with the takeover check around each tool batch, strict tool names, short results and a call log."""
    rounds = 0

    def bind(self, reader, references: list[dict], record, run_id: str | None, purpose: str | None) -> None:
        self.reader, self.record, self.run_id = reader, record, run_id
        self.references, self.purpose = {row['key'] for row in references}, purpose or 'Requested search'

    def check_continuation(self) -> None:
        from relay_core.ai.service import check_continuation
        check_continuation(self.run_id)

    def run_tools(self, calls):
        self.rounds += 1
        self.check_continuation()
        results = super().run_tools(calls)
        # AgentRun starts the next model turn immediately after this returns.
        self.check_continuation()
        return results

    def run_tool(self, call):
        from relay_core.ai.adapter import model_json
        self.check_continuation()
        started = time.monotonic()
        try:
            arguments = model_json(call['arguments'])
            # Existing single-event providers can still name a declared reference.
            # Normalize it through SEARCH; it never bypasses the declaration gate.
            if call['name'] in self.references:
                arguments = dict(purpose=self.purpose, reference=call['name'], arguments=arguments)
                call = dict(call, name='SEARCH')
            if (call['name'] not in self.tools or not isinstance(arguments, dict)
                    or call['name'] in EXPECTED and set(arguments) != EXPECTED[call['name']]):
                raise ValueError('Invalid event tool call')
        except (ValueError, TypeError, KeyError):
            self.reader.failed = True
            raise ValueError('Invalid search call') from None
        text = super().run_tool(dict(call, arguments=arguments))
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS - len(agent.TRUNCATED)] + agent.TRUNCATED
        self.record.add_call(call['name'], arguments, text, started)
        return text
