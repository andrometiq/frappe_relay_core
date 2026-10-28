// Provider parameter logic adapted from the legacy app; the Relay interface is independent.
import { headerMediaParameter } from "./templateMedia.js";

function parseComponents(template) {
  const value = template?.components;
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function variableNumbers(text) {
  return [...String(text || "").matchAll(/\{\{\s*(\d+)\s*\}\}/g)]
    .map((match) => Number(match[1]))
    .filter(
      (value, index, values) => value > 0 && values.indexOf(value) === index,
    )
    .sort((left, right) => left - right);
}

function variableNames(text) {
  return [...String(text || "").matchAll(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g)]
    .map((match) => match[1])
    .filter((value, index, values) => values.indexOf(value) === index);
}

export function templateParameterDescriptors(template) {
  const descriptors = [];
  for (const [componentIndex, component] of parseComponents(
    template,
  ).entries()) {
    const componentType = String(component?.type || "").toUpperCase();
    if (["HEADER", "BODY"].includes(componentType)) {
      const format = String(component?.format || "TEXT").toUpperCase();
      if (
        componentType === "HEADER" &&
        ["IMAGE", "VIDEO", "DOCUMENT"].includes(format)
      ) {
        descriptors.push({
          key: `${componentType}:${componentIndex}:media`,
          componentType,
          componentIndex,
          kind: "media",
          parameterType: format.toLowerCase(),
          label: `${format[0]}${format.slice(1).toLowerCase()} file`,
          example: "",
        });
        continue;
      }
      const named =
        String(template?.parameter_format || "POSITIONAL").toUpperCase() ===
        "NAMED";
      const examples =
        componentType === "HEADER"
          ? component?.example?.header_text || []
          : component?.example?.body_text?.[0] || [];
      if (named) {
        const namedExamples =
          componentType === "HEADER"
            ? component?.example?.header_text_named_params || []
            : component?.example?.body_text_named_params || [];
        for (const parameterName of variableNames(component?.text)) {
          const example = namedExamples.find(
            (row) => String(row?.param_name || "") === parameterName,
          )?.example;
          descriptors.push({
            key: `${componentType}:${componentIndex}:${parameterName}`,
            componentType,
            componentIndex,
            kind: "text",
            parameterName,
            label: `${componentType === "HEADER" ? "Header" : "Body"} value ${parameterName}`,
            example: String(example || ""),
          });
        }
        continue;
      }
      for (const variable of variableNumbers(component?.text)) {
        descriptors.push({
          key: `${componentType}:${componentIndex}:${variable}`,
          componentType,
          componentIndex,
          kind: "text",
          variable,
          label: `${componentType === "HEADER" ? "Header" : "Body"} value ${variable}`,
          example: String(examples[variable - 1] || ""),
        });
      }
      continue;
    }
    if (componentType !== "BUTTONS") continue;
    for (const [buttonIndex, button] of (component?.buttons || []).entries()) {
      const buttonType = String(button?.type || "").toUpperCase();
      if (buttonType !== "URL" || !variableNumbers(button?.url).length)
        continue;
      descriptors.push({
        key: `BUTTON:${componentIndex}:${buttonIndex}`,
        componentType: "BUTTON",
        componentIndex,
        buttonIndex,
        kind: "text",
        variable: 1,
        label: `${button?.text || `Button ${buttonIndex + 1}`} URL value`,
        example: String(button?.example?.[0] || ""),
      });
    }
  }
  return descriptors;
}

export function buildTemplateComponents(descriptors, values) {
  const components = [];
  const grouped = new Map();
  for (const descriptor of descriptors) {
    const media = descriptor.kind === "media" ? headerMediaParameter(descriptor.parameterType, values?.[descriptor.key]) : null;
    const raw = descriptor.kind === "media" ? media : String(values?.[descriptor.key] || "").trim();
    if (!raw) throw new Error(`${descriptor.label} is required.`);
    if (descriptor.componentType === "BUTTON") {
      components.push({
        type: "button",
        sub_type: "url",
        index: String(descriptor.buttonIndex),
        parameters: [{ type: "text", text: raw }],
      });
      continue;
    }
    const key = descriptor.componentType.toLowerCase();
    if (!grouped.has(key)) grouped.set(key, { type: key, parameters: [] });
    const target = grouped.get(key);
    if (media) {
      target.parameters.push(media);
    } else {
      target.parameters.push({
        type: "text",
        text: raw,
        ...(descriptor.parameterName
          ? { parameter_name: descriptor.parameterName }
          : {}),
      });
    }
  }
  return [...grouped.values(), ...components];
}

function fillPlaceholders(text, descriptors, values, componentType) {
  let result = String(text || "");
  for (const descriptor of descriptors.filter((row) => row.componentType === componentType && row.kind === "text")) {
    const placeholder = descriptor.parameterName || descriptor.variable;
    const value = String(values?.[descriptor.key] || descriptor.example || `{{${placeholder}}}`);
    result = result.replace(new RegExp(`\\{\\{\\s*${placeholder}\\s*\\}\\}`, "g"), () => value);
  }
  return result;
}

const BUTTON_ICONS = { URL: "external-link", PHONE_NUMBER: "phone", COPY_CODE: "copy", OTP: "copy" };

// One WhatsApp-style rendering for the send dialog and the template editor; empty values show the example or the placeholder.
export function templateRendering(template, descriptors, values) {
  const result = { header: "", media: "", mediaUrl: "", body: "", footer: "", buttons: [] };
  for (const component of parseComponents(template)) {
    const type = String(component?.type || "").toUpperCase();
    const format = String(component?.format || "TEXT").toUpperCase();
    if (type === "HEADER" && format === "TEXT") result.header = fillPlaceholders(component.text, descriptors, values, "HEADER");
    else if (type === "HEADER") {
      const chosen = values?.[descriptors.find((row) => row.kind === "media")?.key];
      result.media = format.toLowerCase();
      result.mediaUrl = String(chosen?.link || component?.example?.header_handle?.[0] || "");
    }
    else if (type === "BODY") result.body = fillPlaceholders(component.text, descriptors, values, "BODY");
    else if (type === "FOOTER") result.footer = String(component.text || "").trim();
    else if (type === "BUTTONS") {
      result.buttons = (component.buttons || []).map((button) => {
        const buttonType = String(button?.type || "").toUpperCase();
        return {
          key: button?._client_key,
          text: String(button?.text || "").trim() || (buttonType === "OTP" ? "Copy code" : buttonType),
          icon: BUTTON_ICONS[buttonType] || "corner-up-left",
        };
      });
    }
  }
  if (!result.body && (template?.body_text || template?.name || template?.template_name))
    result.body = String(template.body_text || template.name || template.template_name);
  return result;
}

export function templatePreview(template, descriptors, values) {
  return templateRendering(template, descriptors, values).body;
}
