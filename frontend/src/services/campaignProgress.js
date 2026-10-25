// Campaign progress shown from counters only; rows are paged separately.
export const COUNTERS = [
  ["total", "Recipients"], ["queued", "Waiting"], ["sent", "Sent"], ["delivered", "Delivered"],
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
    Draft: ["start", "cancel"], Running: ["pause", "cancel"], Paused: ["resume", "cancel"],
  }[status] || [];
}

export function statusTheme(status) {
  return { Running: "blue", Completed: "green", Paused: "orange", Cancelled: "gray", Cancelling: "gray", Importing: "blue" }[status] || "gray";
}

export function missingMapping(fields, mapping) {
  if (!mapping?.phone) return ["Phone number"];
  return fields.filter((field) => !mapping.fields?.[field.key] && !String(mapping.fixed?.[field.key] || "").trim())
    .map((field) => field.label);
}
