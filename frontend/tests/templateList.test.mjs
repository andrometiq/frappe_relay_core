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
