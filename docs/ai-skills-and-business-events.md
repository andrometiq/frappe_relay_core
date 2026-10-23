# Relay skills and business events

`frappe_tools` is required. Relay uses its AI Model, AI Provider Account, client and bounded AgentRun engine through `relay_core.ai.adapter`. The extraction-only task API is deliberately not used. Logs use the shared log's supported empty phase and reference the Relay Automation Run, not a business document. No dependency files or provider credentials are copied.

## Configure a skill

In **AI & skills**, choose an AI Model, WhatsApp channel, business DocType, dedicated enabled Relay manager as run-as user, and a handoff owner with conversation access. Configure the fallback owner in Relay Settings. Start in Shadow mode. The existing `relay_automation_enabled` site flag must already be enabled for inbound automation; this change does not edit site configuration.

There can be one enabled skill per channel/business type. Its plain-English instructions define supported work. Unsupported requests and failed model/tool reads go to the same handoff service. Text messages are supported; media requires a human. Imported history does not start automation.

Tools have fixed names, operations, DocTypes, fields and business links. For example:

```json
[
  {
    "name": "supplier_ledger",
    "method": "get_list",
    "doctype": "Payment Ledger Entry",
    "fields": ["name", "party", "posting_date", "amount"],
    "scope_field": "party"
  }
]
```

The service constrains `party` to the conversation's supplier and the Dynamic Link's `party_type` to Supplier. It cannot be overridden by model arguments. A Link must directly target the skill's business DocType; reading the business itself uses `scope_field: "name"`. Child tables, credential/settings DocTypes and sensitive fields are unavailable.

`get_doc` accepts only `name`. `get_list` accepts `limit` (1–20) and filters on configured fields. Filters support scalar equality or `[operator, operand]`, with operators `=`, `>=`, `<=`, and `between`; for example `{"posting_date": ["between", ["2026-10-01", "2026-10-24"]]}`. Every read uses `frappe.get_list` and document permission checks, including installed YRP hooks and field permissions. No raw SQL, arbitrary method, report or URL tool is registered.

A linked Contact.user is authoritative, including when disabled or denied. Only a missing user link falls back to the skill's run-as user. Read results are fingerprinted and reread under that identity before sending and before any journal recovery resubmission. Permission or content changes cause handoff. Empty read results also hand off: a restrictive query hook must not be misrepresented as a zero balance. The loop has a 20-second model deadline, four tool calls, one provider attempt and the skill's daily budget. Existing site worker slots bound automatic concurrent decisions.

The shadow test uses the **saved** skill and an incoming Relay Message reference. It performs real permission-scoped reads and model inference, consumes budget and produces shared model logs. It cannot create a run, send a message, pause automation or create a ticket.

## Handoff and delivery

`relay_core.ai.handoff.handoff()` serializes on the contact, reuses the ticket key for the conversation/ownership generation, selects the configured eligible owner or fallback, and stores business, reason and source run. It pauses the existing contact-level automation ownership and advances its generation, invalidating unsent automation. Other conversations sharing that Relay Contact are also paused, consistent with the existing takeover service. Closing a ticket does not automatically resume AI.

If both owners are unavailable, automation remains paused and the pending run records the configuration problem for recovery. It never creates an unassigned ticket. Fix the owner/access configuration before resuming.

AI text uses `messaging.send` with a stable action key and source run, so the normal Relay Message Action journal creates history and tracks receipts. Decisions are saved before sending and reused after crashes. Uncertain delivery remains journal-owned; it is never blindly retried. Legacy Relay AI Provider, policy, outbox and run records are retained. New inbound decisions require a skill; pending legacy runs route to a human (or finish Shadow). Existing legacy outboxes keep their journal reconciliation path. Ancillary legacy JSON tasks now require an AI Model on their policy. Image inference through that compatibility path is unavailable.

## Business events

**Business events** configures a source DocType, `after_insert` / `on_submit` / `on_cancel`, a Link field resolving its Customer/Supplier/party, channel, run-as user, approved template and ordered source parameters. The business must have exactly one linked Contact; ambiguous or missing recipients are logged instead of guessed. `items_summary` renders item names, quantities and UOM. Zero-valued parameters are retained.

The lifecycle hook captures an immutable intent in the business transaction, keyed by site, source DocType/name, event, rule and recipient. Each rule uses a savepoint. Delivery is enqueued only after commit, and even a queue/logging failure cannot escape the hook. Pending intents survive queue outages for scheduler recovery. Workers recheck the rule version, source/field permissions, business link and template approval, then call the same conversation-start action journal. Source changes before dispatch fail closed. The outgoing message carries its business association into the business chat timeline.

Disabled Delivery Note and Sales Order sample rules are installed by `install_samples()` after install/migration when those ERPNext DocTypes exist. An orchestrator using DocType reloads instead can invoke that idempotent function on the authorized local test site after reloading the new schema. Samples deliberately lack channel, user and approved template until configured.

All three screens use existing Socket.IO invalidations. No polling was added.

## Validation and remaining acceptance

The unit suites exercise two suppliers with non-zero ledger values, dynamic party type collisions, YRP-style query/document denials, changed identities, read revalidation, model failure, shared agent calls, shadow mode, idempotent assigned handoff, journal sends/recovery, event failures and deduplication. Transport and model responses are mocked; these results are not site acceptance.

Before release, the orchestrator must reload the changed/new DocTypes on the exact isolated development site, install the disabled samples, reload web/workers and serve the built assets. Exercise populated Supplier/Customer conversations with YRP, an approved local template and local mocked transport: consent/date-range ledger flow, unauthorized second supplier, unsupported intent, revoked user/permissions, failed model, unavailable handoff owner, duplicate/concurrent callbacks, takeover, Redis outage, uncertain sends and receipt history. Verify the Tickets filters/assignment and both editors at mobile and desktop sizes, including reconnects. Measure reply latency under concurrent inbound messages. No site reload, migration, production mutation or live delivery was performed in this worktree task.
