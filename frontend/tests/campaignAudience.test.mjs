import test from "node:test";
import assert from "node:assert/strict";
import { audienceSummary, cleanAudience, dropContact, emptyAudience, inputTime, missingValues, pickContact, recipientLabel,
  scheduleNotice, siteTime, valueOptions } from "../src/services/campaignAudience.js";
import { campaignActions, statusTheme } from "../src/services/campaignProgress.js";

test("only set filters reach the server and segments need a linked record type", () => {
  assert.deepEqual(cleanAudience(emptyAudience()), {});
  const audience = { ...emptyAudience(), tag: "VIP", number: "+91 98-7", segments: { territory: "South", customer_group: "" }, include: ["RELAY-CON-1"] };
  assert.deepEqual(cleanAudience(audience), { tag: "VIP", number: "91987", include: ["RELAY-CON-1"] });
  assert.deepEqual(cleanAudience({ ...audience, doctype: "Customer" }).segments, { territory: "South" });
});

test("a contact added by hand is no longer removed, and the other way round", () => {
  let audience = pickContact(emptyAudience(), "C1", "exclude");
  assert.deepEqual([audience.include, audience.exclude], [[], ["C1"]]);
  audience = pickContact(audience, "C1", "include");
  assert.deepEqual([audience.include, audience.exclude], [["C1"], []]);
  assert.deepEqual(pickContact(audience, "C1", "include").include, ["C1"]);
  assert.deepEqual(dropContact(audience, "C1", "include").include, []);
});

test("the live count names opted-out numbers that will be skipped", () => {
  assert.equal(audienceSummary(null), "");
  assert.equal(audienceSummary({ count: 1, opted_out: 0 }), "1 number matches.");
  assert.equal(audienceSummary({ count: 1250, opted_out: 3 }), "1,250 numbers match. 3 opted out and will be skipped.");
});

test("template values need a source or a fixed value, and media takes only a fixed link", () => {
  const fields = [{ key: "body:name", label: "Body value name" }, { key: "header_media", label: "Header image URL", media: "image" }];
  assert.deepEqual(missingValues(fields, { fields: { "body:name": "contact.first_name" }, fixed: {} }), ["Header image URL"]);
  assert.deepEqual(missingValues(fields, { fields: { "body:name": "contact.first_name" }, fixed: { header_media: "https://cdn.example/a.jpg" } }), []);
  const sources = [{ value: "contact.first_name", label: "Contact · First name" }];
  assert.equal(valueOptions(fields[0], sources).length, 2);
  assert.deepEqual(valueOptions(fields[1], sources), [{ value: "", label: "Fixed value" }]);
});

test("rows skipped for opt-out say so", () => {
  assert.equal(recipientLabel({ status: "Skipped", reason: "Opted out" }), "Skipped: opted out");
  assert.equal(recipientLabel({ status: "Skipped", reason: "Invalid phone number" }), "Skipped");
  assert.equal(recipientLabel({ status: "Read", replied_at: "2026-10-27 10:00:00" }), "Replied");
});

test("the schedule keeps the site wall time between the input and the server", () => {
  assert.equal(inputTime("2026-10-28 09:30:00"), "2026-10-28T09:30");
  assert.equal(siteTime("2026-10-28T09:30"), "2026-10-28 09:30:00");
  assert.equal(siteTime(""), "");
  assert.equal(scheduleNotice({ status: "Scheduled", scheduled_at: "2026-10-28 09:30:00", time_zone: "Asia/Kolkata" }),
    "Starts on 2026-10-28 at 09:30 (Asia/Kolkata).");
  assert.equal(scheduleNotice({ status: "Running", scheduled_at: "2026-10-28 09:30:00" }), "");
  assert.deepEqual(campaignActions("Scheduled"), ["start", "unschedule", "cancel"]);
  assert.equal(statusTheme("Scheduled"), "blue");
});
