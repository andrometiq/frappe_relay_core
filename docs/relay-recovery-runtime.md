# Relay-only scheduled recovery

Normal deployments should run Frappe's scheduler and workers. Pilot may deliberately
pause the general scheduler for unrelated installed apps. Relay has an explicit,
site-scoped alternative for that case; it does not change `pause_scheduler`,
`disable_scheduler`, or System Settings.

Set `relay_scoped_recovery_enabled` to `1` in the selected site's configuration.
Run with that bench's Python environment:

```sh
python -m relay_core.recovery_runtime --sites-path /absolute/bench/sites --site example.site
```

`--once` performs one scheduling tick and returns a nonzero status for disabled,
maintenance, missing/stopped jobs or scheduling errors. The continuous process
checks once per minute and reconnects to read current site settings. Use a process
supervisor with restart-on-failure. The current Pilot review service is
`relay-core-yrp-recovery.service` under the user's systemd manager; it is a
transient local service, not a reboot-persistent production deployment.

Only the nine recovery methods explicitly listed in `relay_core.operations.JOBS`
are eligible. Existing Scheduled Job Type records decide when each is due, and
Frappe's queue deduplication prevents duplicate scheduled jobs. Stopped jobs stay
stopped. Maintenance mode prevents scheduling. Existing Relay workers execute
the jobs; AI policy, endpoint, assignment and replay checks remain inside their
normal recovery paths. The process does not directly send provider messages.

Overview shows the runtime's heartbeat and each job's recorded activity to
communication managers. A missing heartbeat expires after three minutes.
A recent job start is not a completion claim; when Scheduled Job Log contains a
corresponding result, Overview can show failure or recent completion. Check
worker/job logs for execution errors. The runtime prints only aggregate scheduling
counts, never provider credentials or customer message content.

To stop this alternative, stop its service and set
`relay_scoped_recovery_enabled` to `0`. Already queued/running jobs follow normal
Frappe worker semantics. If switching to the normal scheduler, disable this
alternative first. Keep the app's scheduled-job registration current during
normal Frappe migration.

Validation uses `integration_recovery_runtime_site.py` for explicit opt-in,
maintenance gating, the exact method allowlist, stopped/missing jobs and heartbeat
failure. Installed Pilot acceptance separately checks a real timed enqueue and
worker cycle with initially empty Relay queues; it does not prove external
provider delivery or recovery under production load.
