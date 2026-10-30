import unittest
from unittest.mock import Mock, patch

from relay_core import hooks, operations, scheduled_jobs


def scheduled_methods():
    events = hooks.scheduler_events
    return [*events['cron']['* * * * *'], *events['cron']['*/10 * * * *'], *events['cron']['30 1 * * *'],
            *events['daily']]


class ScheduledJobTests(unittest.TestCase):
    def test_every_scheduled_job_and_recovery_status_entry_is_gated(self):
        for method in [*scheduled_methods(), *operations.JOBS]:
            with self.subTest(method=method):
                self.assertTrue(method.startswith('relay_core.scheduled_jobs.'))
                self.assertTrue(callable(getattr(scheduled_jobs, method.rsplit('.', 1)[1])))

    def test_without_hub_each_job_reads_one_setting_and_returns(self):
        database = Mock()
        database.get_single_value.return_value = None
        with patch.object(scheduled_jobs.frappe, 'conf', {}), patch.object(scheduled_jobs.frappe, 'db', database), \
             patch.object(scheduled_jobs.frappe, 'get_attr') as get_attr:
            for method in scheduled_methods():
                getattr(scheduled_jobs, method.rsplit('.', 1)[1])()
        get_attr.assert_not_called()
        self.assertEqual(database.mock_calls, [(('get_single_value', ('Relay Settings', 'hub_url'), {}))]
                         * len(scheduled_methods()))

    def test_configured_hub_runs_the_job(self):
        for conf, saved_url in (({}, 'https://hub.example/mcp'), ({'relay_hub_url': 'https://hub.example/mcp'}, None)):
            with self.subTest(conf=conf):
                database = Mock()
                database.get_single_value.return_value = saved_url
                target = Mock()
                with patch.object(scheduled_jobs.frappe, 'conf', conf), patch.object(scheduled_jobs.frappe, 'db', database), \
                     patch.object(scheduled_jobs.frappe, 'get_attr', return_value=target) as get_attr:
                    scheduled_jobs.recover_messages()
                get_attr.assert_called_once_with('relay_core.messaging.recover')
                target.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
