// Provider parameter logic adapted from the legacy app; the Relay interface is independent.
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
    const raw = String(values?.[descriptor.key] || "").trim();
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
    if (descriptor.kind === "media") {
      const media =
        raw.startsWith("http://") || raw.startsWith("https://")
          ? { link: raw }
          : { id: raw };
      target.parameters.push({
        type: descriptor.parameterType,
        [descriptor.parameterType]: media,
      });
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

export function templatePreview(template, descriptors, values) {
  let text = String(
    template?.body_text ||
      parseComponents(template).find(
        (row) => String(row.type).toUpperCase() === "BODY",
      )?.text ||
      template?.name ||
      template?.template_name ||
      "",
  );
  for (const descriptor of descriptors.filter(
    (row) => row.componentType === "BODY",
  )) {
    const value = String(
      values?.[descriptor.key] ||
        descriptor.example ||
        `{{${descriptor.variable}}}`,
    );
    const placeholder = descriptor.parameterName || descriptor.variable;
    text = text.replace(
      new RegExp(`\\{\\{\\s*${placeholder}\\s*\\}\\}`, "g"),
      value,
    );
  }
  return text;
}
