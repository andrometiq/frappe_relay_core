// Bounded RFC 4180 reader; imported values only replace approved content slots.
export function parseCsv(value) {
  if (
    typeof value !== "string" ||
    new TextEncoder().encode(value).length > 512 * 1024
  )
    throw Error("Choose a CSV file up to 512 KiB");
  const rows = [];
  let row = [],
    field = "",
    quoted = false,
    closed = false;
  function cell() {
    row.push(field);
    field = "";
    closed = false;
    if (row.length > 60) throw Error("CSV has too many columns");
  }
  function record() {
    cell();
    if (row.some((value) => value.trim())) rows.push(row);
    row = [];
    if (rows.length > 1001)
      throw Error("A campaign supports up to 1000 CSV recipients");
  }
  value = value.replace(/^\uFEFF/, "");
  for (let i = 0; i < value.length; i++) {
    const char = value[i];
    if (quoted) {
      if (char === '"') {
        if (value[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
          closed = true;
        }
      } else field += char;
      continue;
    }
    if (char === '"') {
      if (field || closed) throw Error("Invalid CSV quoting");
      quoted = true;
    } else if (char === ",") cell();
    else if (char === "\r" || char === "\n") {
      if (char === "\r" && value[i + 1] === "\n") i++;
      record();
    } else {
      if (closed) throw Error("Unexpected text after quoted CSV value");
      field += char;
    }
  }
  if (quoted) throw Error("CSV contains an unclosed quote");
  if (field || row.length || closed) record();
  if (rows.length < 2)
    throw Error("CSV needs a header and at least one recipient");
  const headers = rows.shift().map((value) => value.trim());
  if (headers[0] !== "Contact" || new Set(headers).size !== headers.length)
    throw Error("The first column must be Contact and headers must be unique");
  return rows.map((values, index) => {
    if (values.length !== headers.length)
      throw Error(
        "CSV row " + (index + 2) + " has a different number of columns",
      );
    return Object.fromEntries(headers.map((key, i) => [key, values[i]]));
  });
}
export function slots(campaign) {
  const args =
    typeof campaign.arguments === "string"
      ? JSON.parse(campaign.arguments)
      : campaign.arguments;
  if (campaign.operation === "email.send")return [{key:"Subject",value:args.subject},{key:"Message",value:args.body}];
  if (["messages.send","telegram.send"].includes(campaign.operation))
    return [{ key: "Message", value: args.body }];
  return (args.components || []).flatMap((component, ci) =>
    (component.parameters || []).map((parameter, pi) => ({
      key:
        component.type +
        (component.type === "button" ? "." + component.index : "") +
        "." +
        (parameter.parameter_name || pi + 1),
      ci,
      pi,
      type: parameter.type,
      value:
        parameter.type === "text"
          ? parameter.text
          : parameter[parameter.type]?.link ||
            parameter[parameter.type]?.id ||
            "",
    })),
  );
}
export function recipientsFromCsv(campaign, text) {
  const fields = slots(campaign),
    allowed = new Set(["Contact", ...fields.map((field) => field.key)]);
  const source =
    typeof campaign.arguments === "string"
      ? JSON.parse(campaign.arguments)
      : campaign.arguments;
  const seen = new Set();
  return parseCsv(text).map((row) => {
    for (const key of Object.keys(row))
      if (!allowed.has(key)) throw Error("Unknown CSV column: " + key);
    const contact = row.Contact.trim();
    if (!contact || seen.has(contact))
      throw Error("Each row needs a different Contact reference");
    seen.add(contact);
    const args = JSON.parse(JSON.stringify(source));
    for (const field of fields) {
      if (!(field.key in row)) continue;
      const value = row[field.key];
      if (!value.trim())
        throw Error("Missing " + field.key + " for " + contact);
      if (campaign.operation === "email.send")args[field.key==="Subject"?"subject":"body"]=value;
      else if (["messages.send","telegram.send"].includes(campaign.operation)) args.body = value;
      else {
        const target = args.components[field.ci].parameters[field.pi];
        if (field.type === "text") target.text = value;
        else if (["image", "video", "document"].includes(field.type)) {
          target[field.type] = /^https:\/\//.test(value)
            ? { link: value }
            : { id: value };
        } else throw Error("This parameter cannot be imported: " + field.key);
      }
    }
    return {
      contact,
      arguments:
        campaign.operation === "email.send" ? {subject:args.subject,body:args.body} : ["messages.send","telegram.send"].includes(campaign.operation)
          ? { body: args.body }
          : { components: args.components || [] },
    };
  });
}
export function csvTemplate(campaign, contacts = []) {
  const fields = slots(campaign);
  const quote = (value) =>
    '"' + String(value ?? "").replaceAll('"', '""') + '"';
  return [
    ["Contact", ...fields.map((field) => field.key)],
    ...(contacts.length ? contacts : [{ name: "CONTACT-REFERENCE" }]).map(
      (contact) => [contact.name, ...fields.map((field) => field.value)],
    ),
  ]
    .map((row) => row.map(quote).join(","))
    .join("\r\n");
}
