# Install Core on a test site

This guide installs the Frappe backend and connects it to one Hub account.
It publishes an authenticated `/relay` workspace; automatic replies remain off.

## Prerequisites

- An existing development Bench with a disposable Frappe site. Integration
  simulations use Frappe v16 and PostgreSQL. Other combinations need validation.
- A running Relay Hub with one account whose site URL matches this Frappe site.
- A Hub API token granted to that account, with the scopes your operations need.
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

From the app's `frontend` directory, run:

```sh
npm ci
npm run build:site
```

Restart the site's web workers, then open `/relay`. Guests use the site's normal
Frappe login. The installed workspace exposes connected views only; it does not
load the sample Inbox, dashboard, or flow diagram from the standalone preview.
The app's `public/relay` build must be available through Bench's standard assets
mapping. Rebuild these ignored assets for each frontend release.

## Configure the connection

Run automation on its own worker: `bench worker --queue default`. Run message
and receipt projection separately with `bench worker --queue short,long`.
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


Set these private site configuration values using your normal Frappe
configuration or secret-provisioning process:

| Key | Value |
| --- | --- |
| `relay_hub_url` | Full Hub MCP URL, for example `https://hub.example.com/mcp` |
| `relay_hub_token` | Hub API token for this site's account |
| `relay_hub_account` | Exact Hub account identifier |
| `relay_callback_secret` | Shared callback-signing secret of at least 32 characters |
| `relay_automation_enabled` | `false` until automation is deliberately configured |

These values belong on the server. Do not put them into Vite variables, frontend
bundles, screenshots, or Git. Core permits HTTP Hub URLs only for explicit loopback
IPs, such as `http://127.0.0.1:18081/mcp`; a hostname that resolves locally is not
a loopback-IP exception.

Create a dedicated Frappe API user with `Relay Hub Service` for callbacks. Configure
its API key/secret and the matching callback secret in Hub. Callbacks target
`/api/method/relay_core.inbound.receive` and require Frappe authentication plus the
Hub signature. See [callback contract](authentication.md#hub-callbacks).

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
