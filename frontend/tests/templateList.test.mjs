import assert from "node:assert/strict";
import test from "node:test";
import {
  filterTemplates,
  templateBody,
  templateButtons,
  templateStatusTheme,
} from "../src/services/templateList.js";

const rows = [
  {
    id: "1",
    name: "order_ready",
    language: "en_US",
    category: "UTILITY",
    status: "APPROVED",
    components: [{ type: "BODY", text: "Order {{1}} is ready" }],
  },
  {
    id: "2",
    name: "festival_offer",
    language: "ta",
    category: "MARKETING",
    status: "PENDING",
    components: [
      { type: "BODY", text: "Festival offer" },
      { type: "BUTTONS", buttons: [{ type: "URL", text: "Shop" }] },
    ],
  },
];

test("filters the template list by searchable content and visible facets", () => {
  assert.deepEqual(filterTemplates(rows, { query: "order" }).map((row) => row.id), ["1"]);
  assert.deepEqual(filterTemplates(rows, { query: "festival", status: "PENDING", category: "MARKETING" }).map((row) => row.id), ["2"]);
  assert.equal(filterTemplates(rows, { status: "REJECTED" }).length, 0);
});

test("normalizes preview content and approval colors", () => {
  assert.equal(templateBody(rows[0]), "Order {{1}} is ready");
  assert.equal(templateButtons(rows[1])[0].text, "Shop");
  assert.equal(templateStatusTheme("APPROVED"), "green");
  assert.equal(templateStatusTheme("PENDING"), "amber");
  assert.equal(templateStatusTheme("REJECTED"), "red");
});

test("template sync status reads as one human sentence", async () => {
  const { templateSyncLabel } = await import("../src/services/templateList.js");
  const now = new Date("2026-10-26T10:00:00").getTime();
  assert.equal(templateSyncLabel({ synced_at: null }, now), "Not synced yet");
  assert.equal(templateSyncLabel({ synced_at: "2026-10-26 09:59:40" }, now), "Synced just now");
  assert.equal(templateSyncLabel({ synced_at: "2026-10-26 09:59:00" }, now), "Synced 1 minute ago");
  assert.equal(templateSyncLabel({ synced_at: "2026-10-26 09:57:00" }, now), "Synced 3 minutes ago");
  assert.equal(templateSyncLabel({ synced_at: "2026-10-26 07:00:00" }, now), "Synced 3 hours ago");
  assert.match(templateSyncLabel({ synced_at: "2026-10-20 07:00:00" }, now), /^Synced on /);
});
