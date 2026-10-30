// Campaign progress shown from counters only; rows are paged separately.
export const COUNTERS = [
  ["total", "People"], ["queued", "Pending"], ["sent", "Sent"], ["delivered", "Delivered"],
  ["read", "Read"], ["replied", "Replied"], ["failed", "Failed"], ["skipped", "Skipped"],
];

export function percent(part, total) {
  return total ? Math.min(100, Math.round((100 * (part || 0)) / total)) : 0;
}

export function applyProgress(campaign, event) {
  if (!campaign || !event || event.name !== campaign.name) return campaign;
  return { ...campaign, status: event.status || campaign.status, counts: { ...campaign.counts, ...event.counts } };
}

// A progress event re-reads the open campaign; rows the user paged past the first page stay.
export function mergeCampaign(current, fresh) {
  if (!current || !fresh || current.name !== fresh.name) return current;
  const paged = (current.recipients?.length || 0) > 50;
  return paged ? { ...fresh, recipients: current.recipients, next: current.next } : fresh;
}

// Every approved template across Hub pages (at most 20 pages of 50, like the server check).
export async function approvedTemplates(listPage) {
  const rows = [];
  let after = "";
  for (let index = 0; index < 20; index += 1) {
    const page = await listPage(after);
    rows.push(...(page.data || []));
    after = page.paging?.cursors?.after || "";
    if (!page.paging?.has_more || !after) break;
  }
  return rows.filter((row) => row.status === "APPROVED");
}

export function campaignActions(status) {
  return {
    Draft: ["start", "cancel"], Scheduled: ["start", "unschedule", "cancel"], Running: ["pause", "cancel"], Paused: ["resume", "cancel"],
  }[status] || [];
}

export function statusTheme(status) {
  return { Scheduled: "blue", Running: "blue", Completed: "green", Paused: "orange", Cancelled: "gray", Cancelling: "gray", Importing: "blue" }[status] || "gray";
}

export function missingMapping(fields, mapping) {
  if (!mapping?.phone) return ["Phone number"];
  return fields.filter((field) => !(field.key === 'header_media' && mapping.header_attachment?.files?.length) && !mapping.fields?.[field.key] && !String(mapping.fixed?.[field.key] || "").trim())
    .map((field) => field.label);
}

// Message types a campaign can send: a template, text, or a media kind the WhatsApp channel registry offers.
export function messageTypes(mediaKinds) {
  const media = ["photo", "video", "document"].filter((kind) => mediaKinds.includes(kind));
  return [{ value: "template", label: "Template" }, { value: "text", label: "Text" },
    ...media.map((kind) => ({ value: kind, label: kind[0].toUpperCase() + kind.slice(1) }))];
}

export function campaignMessage(type, text) {
  return type === "text" ? { kind: "text", body: text.trim() } : { kind: type, caption: text.trim() };
}

// Sheet columns a text or caption fills, in first-use order.
export function placeholders(text) {
  return [...new Set([...String(text || "").matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map((match) => match[1]))];
}

export function messageLabel(campaign) {
  if (campaign?.template_name) return campaign.template_name;
  const kind = campaign?.message?.kind;
  return kind ? kind[0].toUpperCase() + kind.slice(1) : { "messages.send": "Text", "messages.media": "Media" }[campaign?.operation] || "—";
}

// Text and media reach only numbers that wrote in the last 24 hours; this is normal, not an error.
export function windowNotice(window) {
  if (!window) return "";
  const total = window.open + window.closed;
  if (!window.open) return `None of these ${total.toLocaleString()} people wrote to you in the last 24 hours, so this message will not reach them. Use an approved template instead.`;
  const reach = `${window.open.toLocaleString()} of ${total.toLocaleString()} people wrote to you in the last 24 hours and will get this message.`;
  return window.closed
    ? `${reach} The other ${window.closed.toLocaleString()} will be skipped. Use an approved template to reach everyone.`
    : reach;
}

// A draft shows only the people count and the skipped rows; every counter shows once sending starts.
export function shownCounters(status, counts) {
  if (status !== "Draft") return COUNTERS;
  return COUNTERS.filter(([key]) => key === "total" || (key === "skipped" && counts?.skipped));
}

// Issues summarize all validated rows, unlike the paged recipient list or old import metadata.
export function invalidNumberLabel(campaign) {
  if (!Array.isArray(campaign?.issues)) return 'Invalid number count unavailable';
  const count = campaign.issues.filter(row => row.reason === 'Invalid phone number').reduce((total, row) => total + Number(row.count), 0);
  if (!Number.isFinite(count)) return 'Invalid number count unavailable';
  return `${count.toLocaleString()} invalid ${count === 1 ? 'number' : 'numbers'}`;
}
