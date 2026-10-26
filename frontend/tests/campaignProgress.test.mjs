import test from "node:test";
import assert from "node:assert/strict";
import { applyProgress, approvedTemplates, campaignActions, campaignMessage, mergeCampaign, messageLabel, messageTypes, missingMapping, percent, placeholders, windowNotice } from "../src/services/campaignProgress.js";

test("progress events merge counters only for the open campaign", () => {
  const campaign = { name: "Winter launch Oct 2026", status: "Running", counts: { total: 5000, sent: 10 } };
  const next = applyProgress(campaign, { name: "Winter launch Oct 2026", status: "Completed", counts: { sent: 4990, read: 12 } });
  assert.deepEqual(next.counts, { total: 5000, sent: 4990, read: 12 });
  assert.equal(next.status, "Completed");
  assert.equal(applyProgress(campaign, { name: "Another campaign", counts: { sent: 1 } }), campaign);
  assert.equal(percent(2500, 5000), 50);
  assert.equal(percent(1, 0), 0);
});

test("actions follow campaign status and mapping reports missing values", () => {
  assert.deepEqual(campaignActions("Draft"), ["start", "cancel"]);
  assert.deepEqual(campaignActions("Completed"), []);
  const fields = [{ key: "header_media", label: "Header image URL" }, { key: "body:name", label: "Body value name" }];
  assert.deepEqual(missingMapping(fields, {}), ["Phone number"]);
  assert.deepEqual(missingMapping(fields, { phone: "Mobile", fields: { "body:name": "Name" }, fixed: { header_media: " " } }), ["Header image URL"]);
  assert.deepEqual(missingMapping(fields, { phone: "Mobile", fields: { "body:name": "Name" }, fixed: { header_media: "https://cdn.example/a.jpg" } }), []);
});

test("a progress re-read refreshes errors and issues but keeps rows paged past the first page", () => {
  const rows = (count) => Array.from({ length: count }, (_, index) => ({ sheet_row: index + 2 }));
  const fresh = { name: "Winter launch Oct 2026", last_error: "Hub rejected this operation: queue is full", issues: [{ reason: "Opted out", count: 3 }], recipients: rows(50), next: 51 };
  assert.equal(mergeCampaign({ name: "Winter launch Oct 2026", recipients: rows(20) }, fresh), fresh);
  const paged = mergeCampaign({ name: "Winter launch Oct 2026", recipients: rows(100), next: 101 }, fresh);
  assert.equal(paged.last_error, fresh.last_error);
  assert.deepEqual(paged.issues, fresh.issues);
  assert.equal(paged.recipients.length, 100);
  assert.equal(paged.next, 101);
  const other = { name: "Another campaign" };
  assert.equal(mergeCampaign(other, fresh), other);
});

test("approved templates are read across every Hub page", async () => {
  const pages = {
    "": { data: [{ name: "a", status: "APPROVED" }, { name: "b", status: "PENDING" }], paging: { cursors: { after: "p2" }, has_more: true } },
    p2: { data: [{ name: "c", status: "APPROVED" }], paging: { cursors: { after: "p3" }, has_more: false } },
  };
  const seen = [];
  const rows = await approvedTemplates(async (after) => { seen.push(after); return pages[after]; });
  assert.deepEqual(rows.map((row) => row.name), ["a", "c"]);
  assert.deepEqual(seen, ["", "p2"]);
});

test("text and media campaigns follow the registry kinds and fill sheet columns", () => {
  assert.deepEqual(messageTypes(["photo", "voice", "document"]).map((row) => row.value), ["template", "text", "photo", "document"]);
  assert.deepEqual(campaignMessage("text", " Hi {{Name}} "), { kind: "text", body: "Hi {{Name}}" });
  assert.deepEqual(campaignMessage("photo", ""), { kind: "photo", caption: "" });
  assert.deepEqual(placeholders("Hi {{Name}}, order {{ Order No }} for {{Name}}"), ["Name", "Order No"]);
  assert.deepEqual(placeholders(""), []);
  assert.equal(messageLabel({ template_name: "notice" }), "notice");
  assert.equal(messageLabel({ message: { kind: "video" } }), "Video");
  assert.equal(messageLabel({ operation: "messages.send" }), "Text");
});

test("the reply window preflight counts numbers and warns about the rest", () => {
  assert.equal(windowNotice(null), "");
  assert.equal(windowNotice({ open: 3, closed: 0 }), "3 of 3 numbers messaged you in the last 24 hours and can get this message.");
  assert.match(windowNotice({ open: 1, closed: 1200 }), /^1 of 1,201 numbers.*1,200 rows will be marked Failed: Outside the 24-hour reply window\.$/);
});
