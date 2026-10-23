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

function validateButton(button, submit) {
  if (!submit) return;
  if (!button.text && !["CATALOG", "OTP"].includes(button.type)) {
    throw new Error("Every button requires visible text.");
  }
  if (button.type === "URL" && !button.url)
    throw new Error("Website buttons require a URL.");
  if (button.type === "PHONE_NUMBER" && !button.phone_number) {
    throw new Error("Phone buttons require a phone number.");
  }
  if (button.type === "FLOW" && !button.flow_id) {
    throw new Error("Flow buttons require a Flow ID.");
  }
  if (button.type === "OTP" && button.otp_type === "ZERO_TAP") {
    if (!button.package_name || !button.signature_hash) {
      throw new Error(
        "Zero-tap OTP buttons require package name and signature hash.",
      );
    }
  }
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
  if (!accountName || !templateName || !languageCode) {
    throw new Error("Account, template name, and language are required.");
  }
  if (!/^[a-z0-9_]{1,512}$/.test(templateName)) {
    throw new Error(
      "Template name must use lowercase letters, numbers, and underscores.",
    );
  }
  if (!["MARKETING", "UTILITY", "AUTHENTICATION"].includes(category)) {
    throw new Error("Template category is invalid.");
  }
  if (!["POSITIONAL", "NAMED"].includes(parameterFormat)) {
    throw new Error("Parameter format is invalid.");
  }
  const ttlValue = String(form.message_send_ttl_seconds || "").trim();
  if (ttlValue && (!/^\d+$/.test(ttlValue) || Number(ttlValue) < 1)) {
    throw new Error("Message send TTL must be a positive number of seconds.");
  }
  if (form.header_type === "TEXT" && !String(form.header_text || "").trim()) {
    throw new Error("Text headers require header text.");
  }
  if (
    submit &&
    ["IMAGE", "VIDEO", "DOCUMENT"].includes(form.header_type) &&
    !String(form.header_media_example || "").trim()
  ) {
    throw new Error(
      "Media headers require a sample handle or URL before submission.",
    );
  }
  if (category !== "AUTHENTICATION" && !String(form.body_text || "").trim()) {
    throw new Error("Template body text is required.");
  }
  if (submit) {
    for (const field of templateSampleFields(form)) {
      if (
        !String(form.sample_values?.[field.scope]?.[field.name] || "").trim()
      ) {
        throw new Error(`${field.label} is required before submission.`);
      }
    }
  }
  for (const button of form.buttons || []) validateButton(button, submit);
  const expiration = String(form.code_expiration_minutes || "").trim();
  if (expiration && (!/^\d+$/.test(expiration) || Number(expiration) < 1)) {
    throw new Error("Code expiration must be a positive number of minutes.");
  }
  const template = {
    account_name: accountName,
    template_name: templateName,
    language_code: languageCode,
    category,
    parameter_format: parameterFormat,
    components: buildTemplateComponents(form),
  };
  if (ttlValue) template.message_send_ttl_seconds = Number(ttlValue);
  return { template_key: templateKey, template, submit };
}
