"""Scenario files: one JSON list per suite, validated before any run."""
import json
import pathlib
import re

from relay_core.ai.sim import personas

DIRECTORY = pathlib.Path(__file__).resolve().parent / 'scenarios'
SUITES = ('core', 'distributor', 'association')
ID = re.compile(r'^(core|distributor|association)\.([a-z][a-z0-9_]*)\.([a-z0-9][a-z0-9_]*)\.(en|ml|hi|ta|mg|tg)$')
SAFETY_GROUPS = frozenset({'other_party', 'injection', 'approval', 'multi_agent'})
CLASSES = frozenset({'reply', 'search_declared', 'handoff', 'decline', 'awaiting_approval', 'cancelled'})
SCENARIO_KEYS = frozenset({'id', 'suite', 'persona', 'language', 'skill', 'turns', 'max_calls', 'max_usd', 'notes'})
TURN_KEYS = frozenset({'in', 'step', 'args', 'decision', 'expect'})
DECISION_KEYS = frozenset({'reply', 'handoff', 'reason', 'data_question', 'decline', 'search',
                           'calls', 'execute', 'match', 'json', 'fault', 'echo'})
EXPECT_KEYS = frozenset({'class', 'skill', 'outbound', 'tool_calls', 'reads', 'oracle', 'contains', 'forbid_text', 'script',
                         'state', 'journals', 'disclosure'})
# Operator steps run between customer turns; run.STEPS implements each.
STEPS = frozenset({'takeover', 'approve', 'reject', 'expire', 'disable_capability', 'duplicate_callback',
                   'disable_user', 'spend_cap', 'write_actions'})


class ScenarioError(ValueError):
    """A scenario file breaks the format in AI-HARNESS-BUILD-SPEC section 5.3."""


def load(path: str | pathlib.Path) -> list[dict]:
    path = pathlib.Path(path)
    rows = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or not rows:
        raise ScenarioError(f'{path.name}: expected a non-empty list of scenarios')
    seen = set()
    for row in rows:
        validate(row)
        if row['id'] in seen:
            raise ScenarioError(f'{row["id"]}: duplicate id')
        seen.add(row['id'])
    return rows


def load_suite(suite: str) -> list[dict]:
    rows = load(DIRECTORY / f'{suite}.json')
    if any(row['suite'] != suite for row in rows):
        raise ScenarioError(f'{suite}.json holds a scenario of another suite')
    return rows


def resolve(value, tokens: dict[str, str]):
    """Replace `{business}`-style tokens in every string; seeded names are known only after the seed."""
    if isinstance(value, str):
        for key, text in tokens.items():
            value = value.replace('{' + key + '}', text)
        return value
    if isinstance(value, list):
        return [resolve(item, tokens) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, tokens) for key, item in value.items()}
    return value


def group(scenario: dict) -> str:
    return scenario['id'].split('.')[1]


def is_safety(scenario: dict) -> bool:
    return group(scenario) in SAFETY_GROUPS


def validate(row: dict) -> None:
    if not isinstance(row, dict) or not isinstance(row.get('id'), str):
        raise ScenarioError('Each scenario is an object with an id')
    fail = lambda message: ScenarioError(f'{row["id"]}: {message}')  # noqa: E731
    match = ID.fullmatch(row['id'])
    if not match:
        raise fail('id must be suite.group.case.lang')
    if set(row) - SCENARIO_KEYS or not {'suite', 'persona', 'language', 'skill', 'turns'} <= set(row):
        raise fail('unknown or missing scenario keys')
    if row['suite'] != match.group(1):
        raise fail('suite differs from the id')
    if row['language'] not in personas.LANGUAGES or personas.LANGUAGE_CODES[row['language']] != match.group(4):
        raise fail('language differs from the id language code')
    try:
        personas.get(row['persona'])
    except KeyError:
        raise fail('unknown persona') from None
    if not isinstance(row['turns'], list) or not row['turns'] or not any('in' in turn for turn in row['turns']):
        raise fail('needs at least one customer turn')
    for index, turn in enumerate(row['turns'], 1):
        validate_turn(turn, lambda message: fail(f'turn {index}: {message}'))


def validate_turn(turn: dict, fail) -> None:
    if not isinstance(turn, dict) or set(turn) - TURN_KEYS:
        raise fail('unknown turn keys')
    if ('in' in turn) == ('step' in turn):
        raise fail('a turn has exactly one of in or step')
    if 'step' in turn:
        if turn['step'] not in STEPS or 'decision' in turn:
            raise fail(f'unknown step {turn["step"]} or a step with a decision')
        if 'expect' in turn:
            validate_expect(turn['expect'], fail)
        return
    if not isinstance(turn['in'], str) or not turn['in'].strip():
        raise fail('in must be customer text')
    decision = turn.get('decision')
    if not isinstance(decision, dict) or set(decision) - DECISION_KEYS or type(decision.get('data_question')) is not bool:
        raise fail('decision needs data_question and known keys only')
    validate_expect(turn.get('expect'), fail)


def validate_expect(expect: dict, fail) -> None:
    if not isinstance(expect, dict) or set(expect) - EXPECT_KEYS or expect.get('class') not in CLASSES:
        raise fail('expect needs a known class and known keys only')
    if 'oracle' in expect and not expect['oracle'].startswith('relay_core.ai.sim.oracles.'):
        raise fail('oracle must be a relay_core.ai.sim.oracles function')
    if 'state' in expect and not all(isinstance(row, list) and len(row) == 2 for row in expect['state'].get('inserted', [])):
        raise fail('state.inserted rows are [doctype, filters]')
    if 'script' in expect and expect['script'] not in set(personas.SCRIPTS.values()):
        raise fail('script must be a detected language')
