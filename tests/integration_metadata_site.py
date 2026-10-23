"""Real Frappe role boundary and cached metadata health; no provider requests."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
root = Path(__file__).resolve().parents[1]
sites = root / '.runtime/automation-bench/sites'
assert Path(os.environ['RELAY_AUTOMATION_TEST_SITES']).resolve() == sites.resolve()
os.chdir(sites)
import frappe
from relay_core import whatsapp
frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name == 'relay_ai_test_20260922' and frappe.conf.db_port == 18433
frappe.connect()
frappe.set_user('Administrator')
try:
    hub = Mock()
    with patch.object(whatsapp, 'checked_client', return_value=(hub, {})) as connection:
        now = datetime.now(timezone.utc)
        for age, expected in [(0, 'ready'), (3, 'stale')]:
            hub.execute.return_value = {'status': 'ready', 'last_success': (now-timedelta(hours=age)).isoformat(), 'templates': [{}, {}], 'profile': {'private': 'not exposed'}, 'last_error': 'not exposed'}
            result = whatsapp.metadata_status()
            assert result['status'] == expected and result['template_count'] == 2
            assert 'profile' not in result and 'last_error' not in result
        for status in ('failed', 'syncing', 'not_synced'):
            hub.execute.return_value = {'status': status, 'truncated': True}
            result = whatsapp.metadata_status()
            assert result['status'] == status and result['truncated']
        hub.execute.return_value = {'status': 'ready', 'last_success': 'invalid'}
        assert whatsapp.metadata_status()['status'] == 'stale'
        assert all(call.args == ({'operation': 'account.metadata'},) for call in hub.execute.call_args_list)
        for user in ('relay-agent-a@example.invalid', 'Guest'):
            frappe.set_user(user)
            before = connection.call_count
            try:
                whatsapp.metadata_status()
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError('Account health disclosed to non-manager')
            assert connection.call_count == before
    print('PASS cached metadata current/stale/failure states, bounded response, manager-only access before Hub calls')
finally:
    frappe.db.rollback()
    frappe.destroy()
