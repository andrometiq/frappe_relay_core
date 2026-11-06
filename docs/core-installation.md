# Install Core on a test site

This guide installs the Frappe backend and connects it to one Hub account.
It publishes an authenticated `/relay` workspace; automatic replies remain off.

## Prerequisites

- An existing development Bench with a disposable Frappe v16 site on MariaDB.
  The automation drain uses session locks on MariaDB and PostgreSQL. Production runs MariaDB.
- A running Relay Hub with one account whose site URL matches this Frappe site.
- A Hub API token granted to that account, with the scopes your operations need.
  WhatsApp bulk campaigns also need `deliveries:cancel`, or a cancel cannot stop queued sends.
  See [authentication](authentication.md).
- A System Manager on the Frappe site.

Packaging requires Python 3.11 or newer; also use the Python version required
by your chosen Frappe release.

## Install and migrate

Run from your development Bench. Replace `relay-test.local` with your disposable
site's name:

```sh
bench get-app --branch develop https://github.com/andrometiq/frappe_relay_core.git
bench --site relay-test.local install-app relay_core
bench --site relay-test.local migrate
bench --site relay-test.local list-apps
```

The installed Python app name is `relay_core`; the repository name is
`frappe_relay_core`. For an existing local checkout, use its path with
`bench get-app` instead. Unpushed changes are not included in a GitHub install.

Expected result: `relay_core` appears in the installed app list. In Desk, search
for `Relay Channel`, `Relay Contact Type`, and `Relay Message`. Migration creates
Relay roles and conversation indexes through `permissions.after_migrate`.

## Build the installed workspace

The standard app build installs the frontend packages and builds the workspace. Run it from the bench, for example `pilot build --apps relay_core` or `bench build --app relay_core`. To build it by hand from the app root, run:

```sh
yarn install --frozen-lockfile
yarn build
```

Restart the site's web workers, then open `/relay`. Guests use the site's normal
Frappe login. The installed workspace exposes connected views only; it does not
load the sample Inbox, dashboard, or flow diagram from the standalone preview.
The app's `public/relay` build must be available through Bench's standard assets
mapping. Rebuild these ignored assets for each frontend release.

## Configure the connection

Run automation on its own worker: `bench worker --queue default`. Run message
and receipt projection separately with `bench worker --queue short,long`.
Each projection queue has one drain per site: a callback wakes it once, and it
projects Pending events in arrival order until none remain. Run `bench migrate`
after deploying it to add the Pending event index.
Do not let a worker consume both `default` and either projection queue: one slow
AI request would then occupy projection capacity. No custom queue configuration
is required. Incoming-message hooks defer policy reads and intent creation until
after the message commits; AI, flows, translations, automatic email replies and
their recovery jobs use `default`. Restart Python web and worker processes after
deploying these backend changes when automatic reload is disabled.

In **Relay → Settings**, a System Manager supplies the Hub MCP URL, account, API
token, and callback signing secret. The token must include `account:read` in
addition to operational scopes. Core verifies the account and site URL through
Hub's `account.get` tool. Set the site's canonical `host_name` to the same origin
registered in Hub. Password fields are encrypted by Frappe, never returned by the
settings read API, and preserved when an edit leaves them blank.

Private site configuration remains supported as a fallback for older installs.

Until a Hub URL is saved in Relay Settings or set as `relay_hub_url`, every Relay scheduled job reads that one value and returns.


Set these private site configuration values using your normal Frappe
configuration or secret-provisioning process:

| Key | Value |
| --- | --- |
| `relay_hub_url` | Full Hub MCP URL, for example `https://hub.example.com/mcp` |
| `relay_hub_token` | Hub API token for this site's account |
| `relay_hub_account` | Exact Hub account identifier |
| `relay_callback_secret` | Shared callback-signing secret of at least 32 characters |
| `relay_automation_enabled` | `false` until automation is deliberately configured |
| `relay_bounded_login_cache` | Optional. `1` replaces Frappe's table-count scan at login with a minimal cache. Off by default; use it only on a development bench where that scan times out. |

These values belong on the server. Do not put them into Vite variables, frontend
bundles, screenshots, or Git. Core permits HTTP Hub URLs only for explicit loopback
IPs, such as `http://127.0.0.1:18081/mcp`; a hostname that resolves locally is not
a loopback-IP exception.

Create a dedicated Frappe API user with `Relay Hub Service` for callbacks. Configure
its API key/secret and the matching callback secret in Hub. Callbacks target
`/api/method/relay_core.inbound.receive` and require Frappe authentication plus the
Hub signature. See [callback contract](authentication.md#hub-callbacks).

## Self-service setup

The Relay provider sets up the Hub once: one Meta app, a Hub container with self-service WhatsApp signup turned on, and a bench enrolment token. After that, each customer site needs only `new-site` and `install-app relay_core`. The customer's System Manager opens `/relay` and follows **Get started** (`/relay#/setup`).

Put these keys in the bench `common_site_config.json`, or in one site's `site_config.json`:

| Key | Value |
| --- | --- |
| `relay_hub_origin` | Hub public origin and prefix, for example `https://hub.example.com` |
| `relay_enrolment_token` | The bench enrolment token from the Hub admin, `relay_enrol_` and 64 hex characters |

Get started has 5 steps:

| Step | What happens |
| --- | --- |
| Connect to Relay | Core creates the `relay-hub@<site>` user with the Relay Hub Service role, sends its API key, a new callback secret and a nonce to `POST {relay_hub_origin}/api/enrol`, and saves the Hub URL, account and token in Relay Settings. The Hub checks the site through `relay_core.onboarding.api.enrolment_proof`. Core then reads the Hub channels and checks the link with `account.get`; **Try again** does both again. Without the config keys, the admin pastes the setup link from the Hub admin, or the bare setup code when the site has `relay_hub_origin`. When `relay_hub_origin` is set, a pasted link must name the same Hub. |
| Business details | The admin checks the business name, email, website, country, time zone, category and WhatsApp display name. Relay Settings keeps them as a draft. |
| WhatsApp number | The admin picks a new number, a WhatsApp Business app number or a number on another provider. A Hub window runs Meta's Embedded Signup. The Hub does the rest; Core keeps a Relay WhatsApp Signup row per session. |
| Test and finish | Core sends Meta's `hello_world` template and shows the payment method, name and limit state. Each **Send** sends a new test. Telegram bots and mailboxes of the site show here too (connect them in Settings > Telegram and Settings > Email); a site with only those channels can finish without a WhatsApp number. |
| Link records | The checked DocTypes become enabled Relay Contact Types. |

When a number is connected, the admin who started the signup gets the Relay Communication Manager role. Finishing sets **Setup finished** in Relay Settings. A site that already had an enabled channel of any kind at upgrade is marked as finished.

Core sends the site address that the browser used, also behind an HTTPS gateway that sets `X-Forwarded-Proto`. To connect or reconnect from a script or a console, set `host_name` in the site config to the public HTTPS address; without it Core stops with "This site does not know its public address here". **Settings > Reconnect to Relay Hub** asks for a new setup code when the site config has no enrolment token. Manual connection stays available under **Settings > Hub connection > Connect manually (advanced)**.

For a WhatsApp Business app number, Core imports the copied chats with `legacy_source = "WhatsApp Business app"`, so no AI, flow, ticket or unread count runs on them. Phone contacts become Relay contacts, and messages sent from the phone show as sent messages.

## Configure business contacts

1. Create an enabled `Relay Contact Type` for each allowed business DocType, such
   as Customer or Supplier. The supported contact DocType is Frappe `Contact`.
2. Link existing Contacts to those business records using standard Dynamic Links.
3. Create exactly one enabled `Relay Channel` for each account/provider pair,
   with the same account identifier as `relay_hub_account`. Ambiguous channel
   mappings are rejected.
4. Create a `Relay Contact` projection referring to the existing Contact.
5. As System Manager, establish `Relay Contact Endpoint` records for the verified
   channel addresses or group chat IDs that belong to that projection.

An incoming address is not trusted just because its phone/email text matches a
Contact. Unknown endpoints remain uncategorized until mapped and verified.
Multiple Contacts may link to one business record; one Contact may link to several
business records. Automation refuses ambiguous business scope.

## Check the installation

Sign in with a Relay role plus permission to the relevant Contact and business
records. The [contacts API](api-reference.md) should return a bounded page,
possibly empty. Resolve role/document permission errors before testing sends.

Use [local simulations](testing.md) before configuring real delivery.
Keep the normal Frappe workers and scheduler running for event projection and
recovery. Verify a signed callback, its persisted event, and its projection before
acceptance. The separate design preview is not the installed workspace.
