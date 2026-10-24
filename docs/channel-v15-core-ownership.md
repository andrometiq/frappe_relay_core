# Channel ownership and starts

Email conversation keys include the channel, verified sender endpoint and email
thread root. Core retains In-Reply-To, References, To/CC and Hub authentication
evidence. Known reply ancestry inherits the existing thread and business;
conflicting or unlinked business ancestry stays in triage. Legacy messages without
a stored thread root resolve through their validated ancestry; traversal is
bounded and rejects cycles or conflicting roots. Subject text never
selects a thread. Forwarding starts a new thread at the actual destination and
requires a readable business linked to that destination. Pre-v1.5 forward actions
without a destination snapshot retain their original source-ownership semantics
and provider request key; recovery still checks source and recipient permissions. Reply and forward
attachments retain their source permission checks.

A verified person can have WhatsApp, Telegram and email endpoints. Enrollment
uses an authenticated stored callback and an explicit linked business. Email
case and Telegram numeric formatting normalize before uniqueness checks;
WhatsApp phone formatting normalizes without rewriting opaque group IDs.
Ordinary saves preserve existing formatted endpoint/key values so old bindings
can still be revoked and reactivated. Administrators can explicitly call the
endpoint document's `canonicalize` method to upgrade an identity with uniqueness
validation. Bindings cannot change owner or channel. Managers can revoke them;
re-enrollment cannot silently restore a revoked binding. Enrollment and uniqueness
validation scan canonical aliases of legacy bindings, including revoked uppercase
email addresses and formatted phone numbers, without rewriting stored identities. Contact details expose
all readable channels, including revocation status.

Ambiguous private Telegram and authenticated email conversations use the shared
business routing state and durable Message Action journal. The sender replies
with the **exact whole-body `relay-business:…` token** within 24 hours. Email
selection is bound to its thread and requires Hub authentication status `pass`.
The prompt sends only to the sender, without copying inbound To/CC recipients.
Automatic mail does not trigger prompts. Ambiguous Telegram groups remain in
administrator triage; a participant never selects the group's business. Reply/topic,
endpoint and channel scope prevent another conversation from consuming a token.
Prompts use after-commit dispatch and authenticated outcome callbacks, including
pending receipts and recovery under the original request key. Submitted email
prompt identifiers resolve through the scoped action/routing journal, including
replies containing only In-Reply-To without References.

New conversation APIs use existing verified destinations. Telegram private
starts accept text; email starts accept subject/body/optional HTML. Ambiguous
business membership requires an explicit selection. Business starts no longer
create endpoint bindings from a Contact phone field. Telegram group sends accept
explicit business arguments and validate reply ownership and topic. Changed
content/business/channel under an existing conversation-start key is rejected.
The public WhatsApp send API selects the verified endpoint matching the prepared
destination, preserving sends with several WhatsApp numbers and other channels.
The legacy WhatsApp history API now reads Core messages for the selected business
through Frappe permissions before pagination. Its numeric cursors identify Core
message sequence numbers; clients should start a fresh history cursor after upgrade.

Message queries retain business permissions. Action audit reads are limited to
the owner and the currently readable business (Administrator can recover all
actions). Legacy actions without business snapshots resolve through a readable,
unambiguous source message in both document and query permissions. Entirely empty
snapshots also recover through their source; partial snapshots remain invalid. Telegram's
pending API applies action permissions to every payload after business access
revocation. Raw Hub events, routing states and other internal payload records are restricted
to Administrator in both document and list hooks. System Manager can configure
Relay but receives no business-content or legacy-triage bypass.
Unowned enrollment previews are Administrator-only; known bindings (including
revoked bindings) also require permission for every possible business owner.
BCC stays in the restricted action audit, outside message history. No business
Link/Dynamic Link fields or lifecycle blockers were added.

Ticket notification sends derive a single permission-checked business from the
ticket and its source messages, then persist it in the email/Telegram action.
Recovery validates the current ticket business against that snapshot. Shared
Customer/Supplier contacts and authorized staff's separately linked personal
contacts work without guessing. Recipient authorization is independent of ticket
ownership. Outgoing history and action snapshots retain the ticket business;
access to the recipient's personal business alone never reveals ticket content.
Changed or ambiguous ticket ownership prevents a new admission. Late provider
success receipts still record delivery after rejection or unsubscribe.

## Local validation

Run from this worktree with the bench interpreter and these environment values:

```sh
export FRAPPE_STREAM_LOGGING=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/sakthi/development/relay-wt/core-c2
export RELAY_AUTOMATION_TEST_SITES=/home/sakthi/development/pilot/benches/version_16/sites
export RELAY_TEST_SITE=yrp.site
/home/sakthi/development/pilot/benches/version_16/env/bin/python -B -m unittest discover -s tests
```

Site scripts run with that same interpreter and environment:

- `tests/integration_channel_identity_site.py`
- `tests/integration_channel_permissions_site.py`
- `tests/integration_channel_routing_site.py`
- `tests/integration_channel_start_site.py`
- `tests/integration_email_site.py`
- `tests/integration_telegram_recovery_site.py`
- `tests/integration_ticket_notifications_site.py`

All seven passed on `yrp.site`, Frappe 16.52.0. Fixtures include one person linked
to a Customer and Supplier, a restricted user, meaningful message quantities,
three channels, separate email threads and another recipient. Tests exercise
signed callback ingress, projection, permission-filtered reads, durable sends,
replay, expiry, revocation, a 12-callback pending-choice burst, competing email
recovery workers, callback races, shared-identity ticket notifications and
business update/delete/cancel link guards. Regression coverage includes actual
Customer/Supplier permission revocation, pre-snapshot WhatsApp action restoration
and recovery, formatted stored endpoints, three-channel public WhatsApp sends,
email choice replies with only In-Reply-To, restricted System Manager raw-event
reads, selected-business WhatsApp history, multiple WhatsApp numbers, revoked
legacy alias re-enrollment, null-snapshot admission, legacy email thread ancestry,
legacy forward recovery, and independently linked staff recipients. Unit coverage
also checks alias lookup beyond 500 bindings and the 100-reference ancestry bound. Site scripts run sequentially:
concurrent fixture creation encountered a tabSeries snapshot conflict; the
sequential final pass succeeded.
They do not delete business records. Test records remain clearly marked local.
Jobs and provider calls are intercepted so external notifications cannot escape.
Repeated runs reached Frappe's hourly user signup throttle. The local fixture
helper bypasses only that throttle while creating `@example.invalid` test users;
Relay permissions, validation and delivery paths remain real. No site configuration
was changed.

No DocType JSON changed or required reload. No migration, fixture export, asset
build, site configuration change, production access, commit or push was run.
**RESTART NEEDED** after the orchestrator integrates the backend and permission
hooks into the active installation. Fresh test processes loaded this worktree;
the shared web/worker installation was not changed. Live provider/Hub/browser
acceptance, web/worker activation and full channel-load acceptance remain outside
this local site proof. The unit suite ran 305 tests: 300 passed, three skipped, and the two
pre-existing ffprobe audio errors remained. The separate `test_whatsapp_v1.py`
run passed all 24 tests. `git diff --check` passed.
