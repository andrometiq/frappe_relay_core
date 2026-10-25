import test from "node:test";
import assert from "node:assert/strict";
import { applyProgress, campaignActions, missingMapping, percent } from "../src/services/campaignProgress.js";

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
