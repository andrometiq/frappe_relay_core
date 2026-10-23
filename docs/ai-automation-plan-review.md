# GLM review of the initial Relay AI automation plan

Model: glm-5.3-flash. Review-only request through the configured provider; no source or credentials modified. This is the original critique. The controlling responses are in ai-automation-plan.md under Review amendments. GLM has not separately approved the revised draft.

# Critical Review: Relay AI Automation Plan

## Verdict up front
The plan is unusually disciplined about the hard problems (idempotency, outbox, identity, injection), but it is **not approvable as written**. There are three blockers in the identity/authorization design, one in the outbox contract, and one gap in rollout gating. Amendments below; optional improvements flagged separately.

---

## Blockers

### B1. Contact resolution lacks a trust anchor for email
"Resolve using verified channel/account identity" is coherent for WhatsApp/Telegram (provider-verified endpoints) but email has no equivalent — SMTP `From` is fully forgeable. The plan acknowledges this ("email sender matching alone must not authorize sensitive report delivery") but then defers "define verification and re-verification" to later. That's a placeholder, not a design, and email is in the build order (step 5).
**Amendment:** Specify the mechanism now: inbound email matched to a contact only after (a) the endpoint carries a verification state (`verified` / `pending` / `unverified`) set via outbound confirmed challenge or prior inbound reply to a verified thread, and (b) each action class declares a minimum verification level. Unclassified/unverified email gets handoff only. Also state SPF/DKIM/DMARC verdict handling explicitly — a DKIM-passing spoof of a customer domain will otherwise pass "verified channel identity."

### B2. Ticket creation is not covered by the idempotency/replay story consistently
The stable action key covers *actions*, and run states cover workers, but the plan doesn't state what happens when the **decision itself is reprocessed** after a crash between "Validated" and "Applying" commit, or on event redelivery after a completed run. Section 4 says "retries must not recreate a ticket," but the guarantee mechanism (which unique key covers the *ticket*?) is unstated.
**Amendment:** Derive the ticket's natural key from the same triple (source event, purpose, slot) with a unique constraint on Relay Ticket, so ticket creation and action record are idempotent under the same key discipline. Add an explicit test: redeliver the original event after Completed → assert no new ticket, action, or outbound intent.

### B3. Outbox "changed payload under existing key = conflict" is under-specified
Who detects the conflict, and what is the resolution? If Hub receives key K with payload P1 (already submitted) and Core retries with P2 (e.g., corrected reply text after a policy change mid-flight), rejecting at Hub leaves the customer with the stale P1 send — is that surfaced to the handoff queue?
**Amendment:** Make the conflict a first-class outcome: Hub responds `409 key_exists(payload_hash)`, Core transitions the action to Failed-with-audit, notifies the assigned team, and links the delivered payload in the run record. Also specify payload immutability enforcement server-side (hash stored at commit; Core refuses to mutate).

### B4. Rollout gating lacks defined entry/exit criteria
"Restricted canary policies → wider enablement" and "establish thresholds from reviewed examples" are intentions without numbers. Plans like this fail at the canary stage because nobody defined what failure looks like.
**Amendment:** Before build step 1 starts, fix: minimum gold-set size per category (e.g., ≥30 labeled cases), max unsafe-action rate (0 in authorization tests — already implied, good), max misdirected-reply rate for canary exit (state a number), canary duration and volume floor, and a named approver role. Without these, "no release on failed tests" is unfalsifiable.

---

## Strong points (verified, not assumed)
- Dedup keys on events, fenced leases, pre-apply rechecks, and "unknown provider outcome not retried with fresh key" correctly address the classic duplicate-send races.
- Per-conversation bot/human ownership + pre-dispatch takeover check closes the double-responder race.
- Rechecking permissions *and* artifact access at download time is right; most plans check only at generation.
- Honest distinction between Hub acceptance and delivery, with submitted/uncertain/failed states, is correct.

## Race/edge cases still unaddressed (should-fix, arguably blockers)
- **Kill switch vs. in-flight outbox dispatch:** "commands take effect before dispatch" — but an outbox row picked up by a worker milliseconds before disable will still send. Need a dispatch-time policy-version check inside the outbox worker, not just at enqueue.
- **Human resume during a queued outbound intent:** resume after handoff may flush a stale queued intent from before takeover. Purge or revalidate queued intents on resume.
- **Lease expiry mid-model-call:** the fencing token story covers claiming, but state what the orphaned worker does on commit-rejection (discard silently vs. audit).

## Optional improvements
- Outbox recovery poll interval and ordering guarantee (per-conversation FIFO) are unstated; fine to decide during implementation.
- Cost/quota accounting across the two model attempts is mentioned but per-conversation burst limits aren't; add later.
- Multilingual evaluation is thin (Tamil/English "initially") — acceptable for v1.

## Bottom line
**Approve conditionally.** B1 (email trust anchor), B2 (ticket idempotency key), B3 (conflict resolution), and B4 (numeric rollout gates) must be written into the plan before build step 1. The architecture is sound; the gaps are all in specification completeness, not design direction.