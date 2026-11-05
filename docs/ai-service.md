# Bench AI service

The bench AI service makes the AI provider calls of Relay AI runs for every site on a bench. Without it, an RQ worker waits for each model turn. With it, a worker builds a turn, hands it to the service and ends. The service result starts a short job that continues the run. The service is off by default.

## How a run uses the service

1. A run job builds each provider turn with frappe_tools (provider, account, model, request body). Relay sends the turn through its own seam (`relay_core.ai.remote.turns`). frappe_tools is not changed.
2. When the site has the service on and the service heartbeat is fresh, the job stores the turn (URL and body, no credentials) and adds a signed entry to the site's Redis stream `relay:ai:requests:<site>`. The job then ends. It does not count as an attempt and its reserved spend is refunded.
3. The service asks the site for the request (`relay_core.ai.remote.site.request`). The site adds the current credentials. The service calls the provider and posts the raw answer and the provider latency back (`relay_core.ai.remote.site.result`).
4. The result enqueues the run at the front of the queue. The job replays the earlier turns from their stored results, runs tool calls such as SEARCH in the site as the run's execution user, and hands over the next turn.

Each stage of a run (Matching, then Event or Search) keeps one deadline across all its jobs: 40 seconds for matching and 60 seconds for a reply. Time in the service queue counts. A handed turn must be answered before the deadline; when it is not, the run fails and goes to staff. A job that ends without a hand-over clears the deadline, so a later attempt gets a new one.

The AI call log shows each turn once, with the provider latency that the service measured.

When the service is down, turns run in the worker as before. A request that the service loses or does not answer in time fails its run, and the conversation goes to staff.

## Turn the service on for a site

Add these keys to the site's `site_config.json`:

```json
{
  "relay_ai_service": 1,
  "relay_ai_service_secret": "<a random value of at least 32 characters>"
}
```

Use a different secret for each site. The service reads `sites/*/site_config.json` every 5 seconds. Frappe can keep the old site configuration for up to 60 seconds. To turn the service off, set `relay_ai_service` to `0`.

## Run the service

Run one service per bench:

```sh
cd /path/to/bench/sites
../env/bin/python -m relay_core.ai.remote.daemon --sites /path/to/bench/sites --callback http://127.0.0.1:8000
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--sites` | required | The bench `sites` folder. |
| `--callback` | required | The bench web server. Use the gunicorn address (`webserver_port`), not the public URL. |
| `--redis` | `redis_queue` of `common_site_config.json` | Redis that holds the request streams. |
| `--site-limit` | 20 | Provider calls in flight for one site. |
| `--total-limit` | 200 | Provider calls in flight for the bench. |

Run it under a process manager that restarts it. The app has two templates in `relay_core/ai/remote/deploy/`:

- `supervisor.conf`: a supervisor program. Replace `BENCH_PATH`, `BENCH_USER` and `WEB_PORT`, add it to the bench supervisor configuration, then run `sudo supervisorctl reread && sudo supervisorctl update`.
- `relay-ai-service.service`: a systemd unit. Replace the same values, copy it to `/etc/systemd/system/`, then run `sudo systemctl daemon-reload && sudo systemctl enable --now relay-ai-service`.

The service stops within 40 seconds of `SIGTERM`. It writes its log to standard error; the supervisor template sends it to `logs/relay-ai-service.log`. The log never contains credentials or message text.

## Check the service

A user who can change Relay Settings can read the health of the service for the current site:

```sh
curl -s -H "Authorization: token <api key>:<api secret>" \
  https://example.com/api/method/relay_core.ai.remote.site.health
```

| Field | Meaning |
| --- | --- |
| `enabled` | The site has the service on. |
| `alive` | The service heartbeat is less than 15 seconds old. |
| `heartbeat_age_s`, `consumer` | Age of the last heartbeat and the host and process of the service. |
| `site_in_flight` | Provider calls in flight for this site. |
| `service_in_flight`, `service_queued`, `service_counts` | Bench totals: calls in flight, entries in work, and done, error, rejected and unreported counts since the service started. |
| `stream_length`, `unacknowledged` | Entries in this site's stream, and entries that the service read but did not finish. |
| `waiting_turns`, `overdue_turns` | Handed turns that wait for a result, and those past their deadline. The per-minute recovery fails overdue turns. |

The health shows no data of other sites. Without a fresh heartbeat, `alive` is false and turns run in the workers.

## Failure handling

| Event | Result |
| --- | --- |
| Service not running when a turn is built | The turn runs in the worker. |
| Service stops while it works on a turn | A restarted service takes over the entry after 120 seconds. A third delivery fails the turn without a provider call. |
| No answer before the stage deadline | The per-minute recovery fails the turn as a timeout. The run goes to staff. |
| Provider error or timeout | The run sees the same error as a direct call. |
| Repeated result | It is ignored. Replies are journaled with a request key, so no reply is sent twice. |
| Forged or expired entry or callback | It is refused. Each site signs with its own secret. |
