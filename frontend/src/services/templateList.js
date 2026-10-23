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
  { query = "", status = "ALL", category = "ALL" } = {},
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
