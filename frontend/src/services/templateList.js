function text(value) {
  return String(value || "").trim();
}

export function templateComponent(template, type) {
  return (Array.isArray(template?.components) ? template.components : []).find(
    (component) => text(component?.type).toUpperCase() === type,
  );
}

export function templateBody(template) {
  return text(templateComponent(template, "BODY")?.text);
}

export function templateHeader(template) {
  const header = templateComponent(template, "HEADER");
  if (!header) return "";
  return text(header.text) || text(header.format);
}

export function templateFooter(template) {
  return text(templateComponent(template, "FOOTER")?.text);
}

export function templateButtons(template) {
  const buttons = templateComponent(template, "BUTTONS")?.buttons;
  return Array.isArray(buttons) ? buttons : [];
}

export function templateStatusTheme(status) {
  const value = text(status).toUpperCase();
  if (value === "APPROVED" || value === "ACTIVE") return "green";
  if (value === "REJECTED" || value === "PAUSED" || value === "DISABLED")
    return "red";
  if (value === "PENDING" || value === "IN_APPEAL") return "amber";
  return "gray";
}

export function filterTemplates(
  templates,
  { query = "", status = "ALL", category = "ALL", language = "ALL" } = {},
) {
  const needle = text(query).toLocaleLowerCase();
  return (Array.isArray(templates) ? templates : []).filter((template) => {
    if (status !== "ALL" && text(template.status).toUpperCase() !== status)
      return false;
    if (
      category !== "ALL" &&
      text(template.category).toUpperCase() !== category
    )
      return false;
    if (language !== "ALL" && text(template.language) !== language) return false;
    if (!needle) return true;
    return [
      template.name,
      template.language,
      template.category,
      template.status,
      templateBody(template),
    ]
      .map((value) => text(value).toLocaleLowerCase())
      .some((value) => value.includes(needle));
  });
}

// One sentence for the scheduled local template copy, e.g. "Synced 3 minutes ago".
export function templateSyncLabel(status, now = Date.now()) {
  if (status?.syncing) return "Syncing with Meta…";
  const date = new Date(String(status?.synced_at || "").replace(" ", "T"));
  if (!Number.isFinite(date.getTime())) return "Not synced yet";
  const minutes = Math.floor(Math.max(0, now - date.getTime()) / 60000);
  const plural = (count, unit) => `${count} ${unit}${count === 1 ? "" : "s"} ago`;
  if (minutes < 1) return "Synced just now";
  if (minutes < 60) return "Synced " + plural(minutes, "minute");
  if (minutes < 1440) return "Synced " + plural(Math.floor(minutes / 60), "hour");
  return "Synced on " + date.toLocaleDateString([], { day: "numeric", month: "short" });
}
