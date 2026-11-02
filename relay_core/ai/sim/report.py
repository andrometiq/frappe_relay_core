"""Run report (spec 5.5): JSON and a Markdown summary with the same numbers, plus the process exit code."""
import json
import pathlib
from collections import defaultdict

from relay_core.ai.sim.checks import is_safety_failure

GATED_TIERS = ('fake', 'replay')


def build(*, suite: str, tier: str, site: str, k: int, results: list[dict], commits: dict, capabilities: dict) -> dict:
    """`results` rows: id, language, safety (bool), passed, trials, failed_checks, state_diff, cost_usd, seconds."""
    by_language = defaultdict(lambda: {'passed': 0, 'failed': 0})
    for row in results:
        by_language[row['language']]['passed' if row['passed'] else 'failed'] += 1
    passed = sum(1 for row in results if row['passed'])
    summary = {'scenarios': len(results), 'passed': passed, 'failed': len(results) - passed,
               'by_language': dict(by_language), 'safety_failures': sum(1 for row in results if is_safety_result(row)),
               'cost_usd': round(sum(row.get('cost_usd', 0) for row in results), 6)}
    return {'suite': suite, 'tier': tier, 'site': site, 'k': k, 'core_commit': commits.get('core'),
            'adapter_commit': commits.get('adapter'), 'capabilities': capabilities, 'summary': summary,
            'results': [{key: row[key] for key in ('id', 'passed', 'trials', 'failed_checks', 'state_diff', 'cost_usd', 'seconds')}
                        for row in results]}


def is_safety_result(row: dict) -> bool:
    """A failed safety-group scenario, or any scenario failing a safety check."""
    return not row['passed'] and (row.get('safety') or any(is_safety_failure(check) for check in row['failed_checks']))


def exit_code(report: dict) -> int:
    summary = report['summary']
    if summary['safety_failures'] or (report['tier'] in GATED_TIERS and summary['failed']):
        return 1
    return 0


def markdown(report: dict) -> str:
    summary = report['summary']
    lines = [f"# AI harness: {report['suite']} ({report['tier']})", '',
             f"Site {report['site']}, k={report['k']}, core {report['core_commit']}, adapter {report['adapter_commit']}.", '',
             f"- Scenarios: {summary['scenarios']}", f"- Passed: {summary['passed']}", f"- Failed: {summary['failed']}",
             f"- Safety failures: {summary['safety_failures']}", f"- Cost USD: {summary['cost_usd']}", '',
             '| Language | Passed | Failed |', '|---|---|---|']
    lines += [f'| {name} | {row["passed"]} | {row["failed"]} |' for name, row in sorted(summary['by_language'].items())]
    failed = [row for row in report['results'] if not row['passed']]
    if failed:
        lines += ['', '## Failed', '']
        lines += [f"- {row['id']}: " + '; '.join(f"turn {check.get('turn')} {check['check']}" for check in row['failed_checks'])
                  for row in failed]
    return '\n'.join(lines) + '\n'


def write(report: dict, directory: pathlib.Path, stamp: str) -> tuple[pathlib.Path, pathlib.Path]:
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{report['suite']}-{report['tier']}-{stamp}"
    json_path, markdown_path = base.with_suffix('.json'), base.with_suffix('.md')
    json_path.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    markdown_path.write_text(markdown(report), encoding='utf-8')
    return json_path, markdown_path
