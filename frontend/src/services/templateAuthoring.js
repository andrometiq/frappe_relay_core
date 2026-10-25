// Functional template transformations adapted from frappe_whatsapp_core; Relay has its own editor UI.
const DEFAULT_COMPONENTS = [{ type: "BODY", text: "" }];
const STANDARD_COMPONENTS = new Set(["HEADER", "BODY", "FOOTER", "BUTTONS"]);

export const TEMPLATE_BUTTON_TYPES = [
  { label: "Quick reply", value: "QUICK_REPLY" },
  { label: "Open website", value: "URL" },
  { label: "Call phone number", value: "PHONE_NUMBER" },
  { label: "Copy offer code", value: "COPY_CODE" },
  { label: "One-time password", value: "OTP" },
  { label: "Open WhatsApp Flow", value: "FLOW" },
  { label: "Open catalog", value: "CATALOG" },
  { label: "Request voice call", value: "VOICE_CALL" },
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function parseTemplateComponents(value, { allowEmpty = false } = {}) {
  let parsed = value;
  try {
    if (typeof value === "string") parsed = JSON.parse(value || "[]");
  } catch (_error) {
    throw new Error("Stored template components contain invalid data.");
  }
  if (!Array.isArray(parsed) || (!allowEmpty && !parsed.length)) {
    throw new Error("Template components must be a non-empty list.");
  }
  parsed = clone(parsed);
  for (const component of parsed) {
    if (
      !component ||
      typeof component !== "object" ||
      Array.isArray(component)
    ) {
      throw new Error("Every template component must be an object.");
    }
    const type = String(component.type || "")
      .trim()
      .toUpperCase();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(type)) {
      throw new Error("Every template component requires a valid Meta type.");
    }
    component.type = type;
  }
  if (!parsed.some((component) => component.type === "BODY")) {
    throw new Error("A BODY component is required.");
  }
  return parsed;
}

function component(components, type) {
  return components.find((row) => row.type === type) || null;
}

function positionalVariables(text) {
  return [...String(text || "").matchAll(/\{\{\s*(\d+)\s*\}\}/g)]
    .map((match) => match[1])
    .filter((value, index, rows) => rows.indexOf(value) === index)
    .sort((left, right) => Number(left) - Number(right));
}

function namedVariables(text) {
  return [
    ...String(text || "").matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g),
  ]
    .map((match) => match[1])
    .filter((value, index, rows) => rows.indexOf(value) === index);
}

function variables(text, parameterFormat) {
  return parameterFormat === "NAMED"
    ? namedVariables(text)
    : positionalVariables(text);
}

function readTextExamples(target, scope, text, parameterFormat) {
  const values = {};
  const names = variables(text, parameterFormat);
  const example = target?.example || {};
  if (parameterFormat === "NAMED") {
    const rows = example[`${scope}_text_named_params`] || [];
    for (const row of rows) {
      if (row?.param_name) values[row.param_name] = String(row.example || "");
    }
  } else {
    const raw = example[`${scope}_text`] || [];
    const rows = scope === "body" && Array.isArray(raw[0]) ? raw[0] : raw;
    names.forEach((name, index) => {
      values[name] = String(rows[index] || "");
    });
  }
  return values;
}

function buttonForm(row = {}, index = 0) {
  const type = String(row.type || "QUICK_REPLY").toUpperCase();
  return {
    ...clone(row),
    type,
    text: String(row.text || ""),
    otp_type: String(row.otp_type || "COPY_CODE").toUpperCase(),
    flow_action: String(row.flow_action || "navigate"),
    example_value: Array.isArray(row.example)
      ? String(row.example[0] || "")
      : String(row.example || ""),
    _original_type: type,
    _client_key: `${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
  };
}

export function templateForm(row = {}, accounts = []) {
  const componentSource = Object.prototype.hasOwnProperty.call(
    row,
    "components",
  )
    ? row.components
    : DEFAULT_COMPONENTS;
  const components = parseTemplateComponents(componentSource);
  const header = component(components, "HEADER");
  const body = component(components, "BODY") || { type: "BODY", text: "" };
  const footer = component(components, "FOOTER");
  const buttons = component(components, "BUTTONS");
  const parameterFormat = String(
    row.parameter_format || "POSITIONAL",
  ).toUpperCase();
  return {
    account_name: row.account_name || accounts[0]?.account_name || "",
    template_name: row.template_name || "",
    language_code: row.language_code || "en",
    category: row.category || "UTILITY",
    parameter_format: parameterFormat,
    message_send_ttl_seconds: row.message_send_ttl_seconds || "",
    header_type: String(header?.format || "NONE").toUpperCase(),
    header_text: String(header?.text || ""),
    header_media_example: String(header?.example?.header_handle?.[0] || ""),
    body_text: String(body.text || ""),
    footer_text: String(footer?.text || ""),
    add_security_recommendation: Boolean(body.add_security_recommendation),
    code_expiration_minutes: footer?.code_expiration_minutes || "",
    buttons: (buttons?.buttons || []).map(buttonForm),
    sample_values: {
      header: readTextExamples(header, "header", header?.text, parameterFormat),
      body: readTextExamples(body, "body", body.text, parameterFormat),
    },
    canonical_components: components,
    advanced_component_count: components.filter(
      (row) => !STANDARD_COMPONENTS.has(row.type),
    ).length,
  };
}

export function templateSampleFields(form) {
  const format = String(form.parameter_format || "POSITIONAL").toUpperCase();
  return [
    ...variables(
      form.header_type === "TEXT" ? form.header_text : "",
      format,
    ).map((name) => ({
      scope: "header",
      name,
      key: `header-${name}`,
      label: `Header sample for {{${name}}}`,
    })),
    ...variables(form.body_text, format).map((name) => ({
      scope: "body",
      name,
      key: `body-${name}`,
      label: `Body sample for {{${name}}}`,
    })),
  ];
}

export function addTemplateButton(form) {
  form.buttons.push(buttonForm({}, form.buttons.length));
}

function writeTextExamples(target, scope, text, parameterFormat, sampleValues) {
  const names = variables(text, parameterFormat);
  const example = { ...(target.example || {}) };
  delete example[`${scope}_text`];
  delete example[`${scope}_text_named_params`];
  if (names.length) {
    if (parameterFormat === "NAMED") {
      example[`${scope}_text_named_params`] = names.map((name) => ({
        param_name: name,
        example: String(sampleValues?.[name] || "").trim(),
      }));
    } else {
      const values = names.map((name) =>
        String(sampleValues?.[name] || "").trim(),
      );
      example[`${scope}_text`] = scope === "body" ? [values] : values;
    }
  }
  if (Object.keys(example).length) target.example = example;
  else delete target.example;
}

function replaceComponent(components, type, value, include) {
  const index = components.findIndex((row) => row.type === type);
  if (!include) {
    if (index >= 0) components.splice(index, 1);
    return;
  }
  if (index >= 0) components.splice(index, 1, value);
  else {
    const order = { HEADER: 0, BODY: 1, FOOTER: 2, BUTTONS: 3 };
    const before = components.findIndex(
      (row) => (order[row.type] ?? 99) > (order[type] ?? 99),
    );
    if (before >= 0) components.splice(before, 0, value);
    else components.push(value);
  }
}

function normalizedButton(row) {
  const result = row._original_type === row.type ? clone(row) : {};
  for (const fieldname of [
    "url",
    "phone_number",
    "example",
    "otp_type",
    "autofill_text",
    "package_name",
    "signature_hash",
    "flow_id",
    "flow_action",
    "navigate_screen",
    "thumbnail_product_retailer_id",
    "ttl_minutes",
  ])
    delete result[fieldname];
  delete result._client_key;
  delete result._original_type;
  const exampleValue = String(row.example_value || "").trim();
  delete result.example_value;
  result.type = String(row.type || "QUICK_REPLY").toUpperCase();
  result.text = String(row.text || "").trim();
  if (result.type === "URL") {
    result.url = String(row.url || "").trim();
    if (exampleValue) result.example = [exampleValue];
  } else if (result.type === "PHONE_NUMBER") {
    result.phone_number = String(row.phone_number || "").trim();
  } else if (result.type === "COPY_CODE") {
    if (exampleValue) result.example = [exampleValue];
  } else if (result.type === "OTP") {
    result.otp_type = String(row.otp_type || "COPY_CODE").toUpperCase();
    if (result.otp_type !== "COPY_CODE" && row.autofill_text) {
      result.autofill_text = String(row.autofill_text).trim();
    }
    if (result.otp_type === "ZERO_TAP") {
      result.package_name = String(row.package_name || "").trim();
      result.signature_hash = String(row.signature_hash || "").trim();
    }
  } else if (result.type === "FLOW") {
    result.flow_id = String(row.flow_id || "").trim();
    result.flow_action = String(row.flow_action || "navigate");
    if (result.flow_action === "navigate" && row.navigate_screen) {
      result.navigate_screen = String(row.navigate_screen).trim();
    }
  } else if (result.type === "CATALOG") {
    if (row.thumbnail_product_retailer_id) {
      result.thumbnail_product_retailer_id = String(
        row.thumbnail_product_retailer_id,
      ).trim();
    }
  } else if (result.type === "VOICE_CALL") {
    result.ttl_minutes = Number(row.ttl_minutes || 1440);
  }
  return result;
}

export function buildTemplateComponents(form) {
  const components = parseTemplateComponents(
    form.canonical_components || DEFAULT_COMPONENTS,
  );
  const parameterFormat = String(
    form.parameter_format || "POSITIONAL",
  ).toUpperCase();
  const headerType = String(form.header_type || "NONE").toUpperCase();
  const existingHeader = component(components, "HEADER") || { type: "HEADER" };
  if (headerType !== "NONE") {
    const header = { ...existingHeader, type: "HEADER", format: headerType };
    if (headerType === "TEXT") {
      header.text = String(form.header_text || "").trim();
      const example = { ...(header.example || {}) };
      delete example.header_handle;
      header.example = example;
      writeTextExamples(
        header,
        "header",
        header.text,
        parameterFormat,
        form.sample_values?.header,
      );
    } else {
      delete header.text;
      const example = { ...(header.example || {}) };
      delete example.header_text;
      delete example.header_text_named_params;
      const handle = String(form.header_media_example || "").trim();
      if (handle) example.header_handle = [handle];
      else delete example.header_handle;
      if (Object.keys(example).length) header.example = example;
      else delete header.example;
    }
    replaceComponent(components, "HEADER", header, true);
  } else replaceComponent(components, "HEADER", null, false);

  const body = { ...(component(components, "BODY") || {}), type: "BODY" };
  body.text = String(form.body_text || "").trim();
  if (!body.text) delete body.text;
  if (form.add_security_recommendation) body.add_security_recommendation = true;
  else delete body.add_security_recommendation;
  writeTextExamples(
    body,
    "body",
    body.text,
    parameterFormat,
    form.sample_values?.body,
  );
  replaceComponent(components, "BODY", body, true);

  const footerText = String(form.footer_text || "").trim();
  const expiration = String(form.code_expiration_minutes || "").trim();
  const includeFooter = Boolean(footerText || expiration);
  const footer = { ...(component(components, "FOOTER") || {}), type: "FOOTER" };
  if (footerText) footer.text = footerText;
  else delete footer.text;
  if (expiration) footer.code_expiration_minutes = Number(expiration);
  else delete footer.code_expiration_minutes;
  replaceComponent(components, "FOOTER", footer, includeFooter);

  const buttons = (form.buttons || []).map(normalizedButton);
  const buttonComponent = {
    ...(component(components, "BUTTONS") || {}),
    type: "BUTTONS",
    buttons,
  };
  replaceComponent(components, "BUTTONS", buttonComponent, buttons.length > 0);
  return components;
}

const LIMITS = { body: 1024, header: 60, footer: 60, button: 25, url: 2000 };
const BUTTON_LIMITS = { QUICK_REPLY: 10, URL: 2, PHONE_NUMBER: 1, COPY_CODE: 1 };
const PLACEHOLDER = /\{\{\s*([^{}]*?)\s*\}\}/g;

function placeholders(value) {
  return [...String(value || "").matchAll(PLACEHOLDER)].map((match) => match[1]);
}

function formatIssues(label, value, parameterFormat) {
  const names = placeholders(value);
  if (parameterFormat === "NAMED") {
    return names.some((name) => !/^[a-z][a-z0-9_]*$/.test(name))
      ? [`${label} variables must be named like {{customer_name}}: lowercase letters, numbers and underscores.`]
      : [];
  }
  if (names.some((name) => !/^\d+$/.test(name)))
    return [`${label} variables must be numbered like {{1}}.`];
  const numbers = [...new Set(names.map(Number))].sort((left, right) => left - right);
  return numbers.some((number, index) => number !== index + 1)
    ? [`${label} variables must be numbered in order from {{1}} without gaps.`]
    : [];
}

function buttonIssues(form) {
  const buttons = form.buttons || [];
  const issues = buttons.length > 10 ? ["Use at most 10 buttons."] : [];
  for (const [type, limit] of Object.entries(BUTTON_LIMITS)) {
    if (buttons.filter((button) => button.type === type).length > limit)
      issues.push(`Use at most ${limit} ${type.toLowerCase().replaceAll("_", " ")} button${limit > 1 ? "s" : ""}.`);
  }
  buttons.forEach((button, index) => {
    const label = `Button ${index + 1}`;
    const text = String(button.text || "").trim();
    if (!text && !["CATALOG", "OTP"].includes(button.type)) issues.push(`${label} needs visible text.`);
    if (text.length > LIMITS.button) issues.push(`${label} text must be at most ${LIMITS.button} characters.`);
    if (button.type === "URL") {
      const url = String(button.url || "").trim();
      const variables = placeholders(url);
      if (!/^https?:\/\/\S+$/.test(url) || url.length > LIMITS.url)
        issues.push(`${label} needs a website URL starting with https:// (at most ${LIMITS.url} characters).`);
      else if (variables.length > 1 || (variables.length && !/\{\{\s*[^{}]*\s*\}\}$/.test(url)))
        issues.push(`${label} URL can have one variable, only at the end.`);
      else if (variables.length && !String(button.example_value || "").trim())
        issues.push(`${label} needs an example URL value for its variable.`);
    }
    if (button.type === "PHONE_NUMBER" && !/^\+?[0-9]{7,20}$/.test(String(button.phone_number || "").replace(/[ ()-]/g, "")))
      issues.push(`${label} needs a phone number with country code.`);
    if (button.type === "FLOW" && !button.flow_id) issues.push(`${label} needs a Flow ID.`);
    if (button.type === "OTP" && button.otp_type === "ZERO_TAP" && (!button.package_name || !button.signature_hash))
      issues.push(`${label} needs the Android package name and signature hash.`);
  });
  return issues;
}

// Mirrors the Meta review rules that most often reject a submitted template.
export function templateIssues(form, { submit = true } = {}) {
  const issues = [];
  const format = String(form.parameter_format || "POSITIONAL").toUpperCase();
  const category = String(form.category || "").toUpperCase();
  const body = String(form.body_text || "").trim();
  const header = String(form.header_text || "").trim();
  const footer = String(form.footer_text || "").trim();
  if (!String(form.template_name || "").trim() || !String(form.language_code || "").trim())
    issues.push("Template name and language are required.");
  else if (!/^[a-z0-9_]{1,512}$/.test(String(form.template_name).trim()))
    issues.push("Template name must use lowercase letters, numbers and underscores.");
  if (!["MARKETING", "UTILITY", "AUTHENTICATION"].includes(category)) issues.push("Choose a template category.");
  if (!["POSITIONAL", "NAMED"].includes(format)) issues.push("Choose a parameter format.");
  if (category !== "AUTHENTICATION" && !body) issues.push("Message body is required.");
  if (body.length > LIMITS.body) issues.push(`Message body must be at most ${LIMITS.body} characters.`);
  if (/^\{\{[^{}]*\}\}/.test(body) || /\{\{[^{}]*\}\}$/.test(body))
    issues.push("Meta rejects a variable at the very start or end of the body. Add text before and after it.");
  issues.push(...formatIssues("Body", body, format));
  if (form.header_type === "TEXT") {
    if (!header) issues.push("Text headers require header text.");
    if (header.length > LIMITS.header) issues.push(`Header text must be at most ${LIMITS.header} characters.`);
    if (placeholders(header).length > 1) issues.push("Header text can have at most one variable.");
    issues.push(...formatIssues("Header", header, format));
  }
  if (footer.length > LIMITS.footer) issues.push(`Footer must be at most ${LIMITS.footer} characters.`);
  if (placeholders(footer).length) issues.push("Footer cannot contain variables.");
  if (submit && ["IMAGE", "VIDEO", "DOCUMENT"].includes(form.header_type) && !String(form.header_media_example || "").trim())
    issues.push("Upload a header sample file before submission.");
  if (submit) {
    for (const field of templateSampleFields(form)) {
      if (!String(form.sample_values?.[field.scope]?.[field.name] || "").trim())
        issues.push(`${field.label} is required before submission.`);
    }
  }
  const ttl = String(form.message_send_ttl_seconds || "").trim();
  if (ttl && (!/^\d+$/.test(ttl) || Number(ttl) < 1)) issues.push("Message validity must be a positive number of seconds.");
  const expiration = String(form.code_expiration_minutes || "").trim();
  if (expiration && (!/^\d+$/.test(expiration) || Number(expiration) < 1))
    issues.push("Code expiration must be a positive number of minutes.");
  return [...issues, ...(submit ? buttonIssues(form) : [])];
}

function sampled(text, values = {}) {
  return String(text || "").replace(PLACEHOLDER, (match, name) => String(values[name] || "").trim() || match);
}

// WhatsApp-style preview content with the current examples filled in.
export function templatePreview(form) {
  const type = String(form.header_type || "NONE").toUpperCase();
  return {
    header: type === "TEXT" ? sampled(form.header_text, form.sample_values?.header) : "",
    media: ["IMAGE", "VIDEO", "DOCUMENT", "LOCATION"].includes(type) ? type.toLowerCase() : "",
    body: sampled(form.body_text, form.sample_values?.body),
    footer: String(form.footer_text || "").trim(),
    buttons: (form.buttons || []).map((button) => ({
      key: button._client_key,
      text: String(button.text || "").trim() || (button.type === "OTP" ? "Copy code" : button.type),
      icon: { URL: "external-link", PHONE_NUMBER: "phone", COPY_CODE: "copy", OTP: "copy" }[button.type] || "corner-up-left",
    })),
  };
}

export function templateRequest(
  form,
  { templateKey = null, submit = false } = {},
) {
  const accountName = String(form.account_name || "").trim();
  const templateName = String(form.template_name || "").trim();
  const languageCode = String(form.language_code || "").trim();
  const category = String(form.category || "")
    .trim()
    .toUpperCase();
  const parameterFormat = String(form.parameter_format || "POSITIONAL")
    .trim()
    .toUpperCase();
  if (!accountName) throw new Error("Account is required.");
  const issues = templateIssues(form, { submit });
  if (issues.length) throw new Error(issues[0]);
  const ttlValue = String(form.message_send_ttl_seconds || "").trim();
  const template = {
    account_name: accountName,
    template_name: templateName,
    language_code: languageCode,
    category,
    parameter_format: parameterFormat.toLowerCase(),
    components: buildTemplateComponents(form),
  };
  if (ttlValue) template.message_send_ttl_seconds = Number(ttlValue);
  return { template_key: templateKey, template, submit };
}
