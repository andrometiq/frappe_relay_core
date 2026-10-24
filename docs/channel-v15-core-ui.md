# Channel UI, audit items 25–29

The worktree Vue entry exposes WhatsApp, Telegram and email through the
existing Relay components. Configuration and conversation requests use Core
endpoints. No schema, fixture, site configuration or Hub files changed.

Contacts show every permitted identity and its revocation state. Identity rows wrap long endpoints, show relative dates and require confirmation before revoking. Empty select defaults retain their visible labels. Enrollment uses
stored authenticated incoming events; existing raw-event authorization remains
unchanged. System Managers can record Granted/Denied consent and priorities for
one explicitly selected business and person. Shared Customer/Supplier identities
never share consent. Setup distinguishes local channel enablement from observed
provider/callback evidence.

Inbox queries and ingestion cursors include all three channels, with provider
filters, unread counts and badges. Directory business labels come from the latest
readable message, not the first linked business. Reconnect invalidates cached
windows and rechecks every loaded message in bounded batches. Frappe's user
permission socket event clears active content, pending bubbles and cached windows.
Pending journal entries also restore by explicit business scope, including when no contact is selected. There are no polling timers.

The inbox is included in the initial entry bundle so route chunk loading cannot
leave an empty pane. HTTP directory/history reads do not depend on Socket.IO.
The compact directory filter defaults to All channels. Previews use structured
plain message data, matching the thread, instead of HTML-sanitized Long Text.
Legacy HTML-only previews strip tags then decode entities once; Vue still renders
the result as text. Literal entities in structured message data remain unchanged.

Telegram uses the existing source message's reply/topic context and attachment
validation, with 4,096-character text and 1,024-character caption limits. Starts
select a verified endpoint explicitly, including multiple identities on one channel.
Composers store drafts in tab-local session storage under the signed-in user and
source scope. Switching to a scope without a draft clears the old composition.

Email supports reply, reply-all, forward, To/CC/BCC, subject, signature and up to
8 attachments/4 MiB combined. Unknown attempts keep their immutable payload and
request key; recovery uses the same key. BCC remains outside history. CC/BCC and signature details use progressive
disclosure. The bottom composer starts with a small growing message box and is
bounded to keep the thread readable; channel and recipient controls share one row.
The same compact context row gives Telegram more thread space. Status reads
prefer an already projected receipt over stale action status, and expose journal
status when no receipt exists. Labels distinguish Bot accepted, SMTP accepted,
Bounced, Queued, Uncertain and Rejected. Agent read state is not a provider read receipt.

Automation retains the existing read-tool/business-permission boundary and saved
skill shadow test. Editors expose all enabled channels, explicit recipient Contact,
consent-based selection, Telegram text and escaped email subject/body/signature
variants. Uncertain deliveries do not switch channels. Opening an automation editor on mobile scrolls it into view.

## Validation

Use the bench interpreter with `PYTHONDONTWRITEBYTECODE=1`, worktree first in
`PYTHONPATH`, `FRAPPE_STREAM_LOGGING=1`,
`RELAY_AUTOMATION_TEST_SITES=/home/sakthi/development/pilot/benches/version_16/sites`
and `RELAY_TEST_SITE=yrp.site` for site tests. No provider calls escape these tests.

- `npm run build:site` from `frontend` writes this worktree's `relay_core/public/relay`.
- `node --test tests/*.test.js tests/*.test.mjs` from `frontend`.
- Bench Python `-B -m unittest discover -s tests` from the worktree.
- Site scripts: `integration_channel_identity_site.py`,
  `integration_channel_permissions_site.py`, `integration_channel_routing_site.py`,
  `integration_channel_start_site.py`, `integration_email_site.py`,
  `integration_telegram_recovery_site.py`, `integration_ticket_notifications_site.py`,
  `integration_business_events_site.py`, `integration_ai_permissions_site.py`.
- `tests/integration_channel_ui_http.py`: real loopback Frappe HTTP, authenticated
  reads/mutations, guest/role/business denials, all-channel unread/history,
  scoped consent and pending email reload. Representative local fixtures share
  a person between Customer and Supplier with nonzero message content.
- Set `RELAY_CU_BROWSER=1`, `RELAY_CU_BROWSER_FIXTURE` to a private `/tmp` JSON path,
  and `RELAY_PLAYWRIGHT_MODULE` to an installed Playwright Node module when running
  the HTTP script to also run `frontend/tests/browser/channelUI.mjs`.
  It uses a one-time local login link; credentials are never printed. The local
  test process raises only the email-link login throttle during repeated captures;
  authentication remains real and no persistent setting changes.
  `emailSimulation.mjs` now exercises the real Core API, including reload-safe
  drafts, reply-all/forward, attachment upload, actual journaling/projection and
  BCC exclusion from history. Only provider transport is intercepted.

The browser URL is `http://127.0.0.1:8001`, whose running web serves the MAIN
checkout. The test intercepts only that browser's HTTP requests and forwards them
to an isolated worktree WSGI process; asset responses read the worktree build.
This does not activate code in the installed web/workers. Screenshots and overflow/
page-error results are in `/tmp/relay-cu-shots/`, at 1440 and 390 px in light/dark.
These are worktree acceptance artifacts, not deployed-main acceptance.

Polish validation: `npm run build:site` passed; frontend **72 passed**; Python
**341 run**, **336 passed**, **3 skipped**, with the **2 pre-existing ffprobe audio
errors** (`test_audio_duration_and_malformed_media` and
`test_transcription_fixed_host_bounded_json_and_redaction`). The added preview
unit test covers original text, literal entities, legacy HTML and empty content.
The real HTTP/browser suite passed, including preview encoding and business denials.
The nine named site suites passed in the preceding CU implementation validation;
they were not rerun for this layout/preview polish.

Deleted the old captures and generated **36 fresh screenshots** at 1440×1000 and
390×844, light and dark, in `/tmp/relay-cu-shots/`. All were visually reviewed.
`results.json` records **no horizontal overflow, no contact/form clipping and no
page errors**. The browser deliberately closes Socket.IO connections throughout:
conversations, history and sends still work through real Core HTTP. It also checks
the All channels default, safe text rendering of an HTML-like preview, relative
identity dates and cancellation of identity revocation without a mutation.
Email thread/composer heights are **506/260 px** on desktop and **304/261 px** on
mobile; Telegram is **606/160 px** and **430/135 px**, respectively, in both themes.
These are populated local fixture scenarios with provider transport stubbed.

## Activation still required

**RESTART NEEDED** after integration so installed web/workers load the backend.
No DocType JSON changed, so no reload or migration is required. Rebuild the merged
app in its actual bench and re-shoot Contacts/consent, Settings, Inbox, Telegram and
email composers, New conversation, AI & skills and Business events. Verify live
Socket.IO reconnect and permission changes in that activated environment.

The Hub's current Core-facing account metadata does not expose the configured
email From address or Telegram bot identity. Setup/composer identify the configured
channel/account rather than inventing these identities. Reply-all preserves
recorded To/CC and requires explicit recipient review; it cannot automatically
exclude the sending mailbox without trustworthy mailbox identity metadata.
Live provider delivery, mailbox self-address exclusion and installed-process
activation are not claimed by this worktree validation. Local fixture records are
retained; test API users are disabled afterward. No commit or push was performed.
