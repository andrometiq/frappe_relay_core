# Jarvis AI reference review

Reference: https://github.com/aerele/jarvis/tree/15574fe64849b024fe4285bad8c2ed0bfe79ede5

Reviewed using GLM 5.3 Flash through the configured Z.ai endpoint. The long CLI review was stopped after producing no report; a large direct request timed out. The completed GLM review used selected source excerpts, not the entire repository. No reference code was executed and no live integration was tested.

## Decisions after source verification

- Adopt an explicit action registry and server-side permission enforcement. Core owns actions; Hub owns transport.
- Automatic execution is allowed only for configured actions such as ticket creation and approved canned-reply selection. Approval of a reusable policy does not require a human to approve every later permitted message.
- Preserve durable per-incoming-message action keys. A tool receipt identifier alone does not establish exactly-once external side effects. Retry uncertain sends only using the Hub's stable request keys.
- Use after-commit background jobs, bounded snapshots, usage caps and durable activity records. Do not blindly copy “never raises”: transient failures need deliberate retry/dead-letter behavior.
- Compile approved guidance into scoped, versioned rules. Learning never grants additional permissions.
- Report permission alone is insufficient for external contacts. Resolve the linked business record server-side and force its customer/supplier filter. Do not trust a model-supplied party filter or broadly privileged agent identity.
- Return permission-checked artifact references rather than putting large report datasets into model context.
- Jarvis includes separate agent runtimes and model-pool routing; auxiliary trigger calls use OpenRouter directly. This is not evidence of a single native adapter handling every provider everywhere.
- The reference has an AGPL-3.0 license file. This review adopts architectural ideas; no source was copied into Relay implementation.

## GLM report (unmodified; recommendations above take precedence)

## How Jarvis works (as seen in the excerpts)

**AI tools.** Tools live as sibling modules in `jarvis/tools/<name>.py`, each exporting a function named after the file. `jarvis/tools/registry.py` keeps only a `_TOOL_NAMES` tuple and builds the dispatch table via `importlib.import_module`, so adding a tool is "drop in a module + add a name." Tools range from read-only (`get_doc`, `get_list`, `query`, `describe_customizations`, `get_my_access`, `validate_script`, `preview_import`) to mutating/gated ones (`create_doc`, `update_doc`, `delete_doc`, `submit_doc`, `run_import`, `apply_workflow_action`) to artifact producers (`export_query`, `report_pdf`, `export_document`). The registry comments encode a policy: heavy data goes out as files ("reference-not-rows"), not model context.

**Permissions & approvals.** `jarvis/api.py` dispatches every tool call under the real caller via `impersonate(user)` in `_dispatch_from_session`, with `_delegate_capability.resolve` + `tool_denial` enforcing a manifest-snapshot capability contract **before** dispatch — fails closed, records refusals (with scrubbed args) via `audit.record`. Mutual write tools are gated at `apply_workflow_action` "in api.py". Human-in-the-loop is `jarvis/chat/approvals_api.py`: a `Jarvis Approval Request` must be `Pending`; the decision is recorded with a conditional SQL flip (`where status='Pending'`) that closes the double-decide race, then a synthetic user message (`APPROVED/REJECTED: …do not re-ask`) resumes the conversation through the normal `send_message` path, so the agent treats the decision like any chat turn.

**Learning.** `jarvis/learning/compiler.py::compile_domain_skills` is read-only: it selects `Approved`/`Active`, sensitivity-A patterns, groups by domain, budgets bullets (`_select_within_budget`, with `deferred` overflow), derives `allowed_roles` per pattern, and renders skill specs — flipping to Active is "apply's job," not compile's.

**Background jobs.** `jarvis/triggers/llm_action.py::run_llm_action` is a `frappe.enqueue` target flushed by the trigger engine after commit: reloads the trigger, applies a per-trigger per-day Redis cap (`jarvis:trigcap:<name>:<date>`, TTL 2 days, one "Skipped" row at cutoff), fences untrusted data (`_fence_untrusted`), calls `voice.openrouter_complete`, and never raises — failures become Failed activity rows. `jarvis/chat/worker.py` is the RQ job wrapping `turn_handler.handle_chat_send`; heavy reports go background via `_prepared_reports` (`jarvis/tools/run_report.py`).

## Adaptation for Relay + Go messaging Hub

**Automatic tickets.** Mirror `llm_action.py`: enqueue a `frappe.enqueue` job on ticket-creating events; Redis per-queue/per-day caps; fenced event-time snapshot; never raise (failure = status row). The Go Hub consumes a lightweight event (or the Frappe job writes to it via authenticated HTTP) — but **keep the trigger/cap logic in Frappe**, as the excerpts show; don't invent Hub-side scheduling.

**Approved canned replies.** Reuse the approvals pattern verbatim: a Relay Canned Reply doctype with `status='Pending' → Approved` and the conditional-flip SQL to prevent double-approve. Only `Approved` replies are exposed to the agent as a gated tool (à la `apply_workflow_action`'s api.py gate). Compile-time learning parallels `compiler.py`: an explicit, role-scoped compile step renders approved reply templates; nothing flips status implicitly.

**Human handoff.** Mirror `approvals_api.py`'s resume mechanism: the handoff decision is injected as a plain user message through the existing `send_message` path, so the agent never gets privileged semantics — plus an `_may_act_on(conversation)` permission check on whoever decides.

**Customer-scoped reports.** Follow `run_report.py` exactly: named-report execution letting Frappe enforce report permissions internally (translate `frappe.PermissionError` → your `PermissionDeniedError`), never raw SQL composed from model input. Add the Hub boundary equivalent to `_dispatch_from_session`: impersonate the customer-scoped user, resolve a per-session capability snapshot, gate before dispatch, fail closed, and audit refusals with scrubbed args. Keep report **rows out of model context** — return Hub-mediated artifact links (`export_query`-style) with row ceilings that fail closed rather than truncate.
