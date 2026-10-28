// Campaign recipients picked from Relay contacts, and the campaign start time.
import { missingMapping } from "./campaignProgress.js";

export const OPTED_OUT = "Opted out";

export function emptyAudience() {
  return { tag: "", doctype: "", segments: {}, number: "", last_message_from: "", last_message_to: "", include: [], exclude: [] };
}

// The filters the server takes: no empty values, digits only in the number filter.
export function cleanAudience(audience) {
  const result = {};
  for (const key of ["tag", "doctype", "last_message_from", "last_message_to"]) if (audience?.[key]) result[key] = audience[key];
  const number = String(audience?.number || "").replace(/\D/g, "");
  if (number) result.number = number;
  const segments = Object.fromEntries(Object.entries(audience?.segments || {}).filter(([, value]) => value));
  if (result.doctype && Object.keys(segments).length) result.segments = segments;
  for (const key of ["include", "exclude"]) if (audience?.[key]?.length) result[key] = [...audience[key]];
  return result;
}

// Add a contact by hand, or remove one; a contact is never in both lists.
export function pickContact(audience, contact, list) {
  const other = list === "include" ? "exclude" : "include";
  const chosen = audience[list].includes(contact) ? audience[list] : [...audience[list], contact];
  return { ...audience, [list]: chosen, [other]: audience[other].filter((name) => name !== contact) };
}

export function dropContact(audience, contact, list) {
  return { ...audience, [list]: audience[list].filter((name) => name !== contact) };
}

// Nothing is picked until the user sets a filter, adds a contact or chooses everyone on the number.
export function hasAudienceChoice(audience, everyone) {
  const chosen = cleanAudience(audience);
  return everyone || Object.keys(chosen).some((key) => key !== "exclude");
}

export function audienceSummary(preview) {
  if (!preview) return "";
  const count = preview.count.toLocaleString();
  const text = `${count} ${preview.count === 1 ? "number matches" : "numbers match"}.`;
  return preview.opted_out ? `${text} ${preview.opted_out.toLocaleString()} opted out and will be skipped.` : text;
}

export function missingValues(fields, mapping) {
  return missingMapping(fields, { ...mapping, phone: "phone" });
}

// Template values from contacts: a fixed value, or a contact or linked record field. Media takes a fixed link.
export function valueOptions(field, sources) {
  return [{ value: "", label: "Fixed value" }, ...(field.media ? [] : sources)];
}

export function recipientLabel(row) {
  if (row.replied_at) return "Replied";
  return row.status === "Skipped" && row.reason === OPTED_OUT ? "Skipped: opted out" : row.status;
}

// Site time "YYYY-MM-DD HH:mm:ss" and the datetime-local input value "YYYY-MM-DDTHH:mm" hold the same wall time.
export function inputTime(value) {
  return value ? String(value).slice(0, 16).replace(" ", "T") : "";
}

export function siteTime(value) {
  return value ? `${value.replace("T", " ")}:00` : "";
}

export function scheduleNotice(campaign) {
  if (campaign?.status !== "Scheduled" || !campaign.scheduled_at) return "";
  return `Starts on ${inputTime(campaign.scheduled_at).replace("T", " at ")} (${campaign.time_zone || "site time"}).`;
}

// A CSV the user can fill in: the mobile number column, then one column per value the message needs.
export function sampleSheet(fields) {
  const columns = ["mobile number", ...(fields || []).map((field) => field.media ? "image url" : field.name || field.label)];
  const example = ["919876543210", ...(fields || []).map((field) => field.media ? "https://example.com/photo.jpg" : "Example")];
  const cell = (value) => /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  return [columns, example].map((row) => row.map(cell).join(",")).join("\n") + "\n";
}
