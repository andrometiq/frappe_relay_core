import { buildTemplateComponents } from '../../services/templateParameters';
import { nextTick, watch } from "vue";
export function useWhatsAppTemplates({
  editingTemplate,
  templateCursor,
  bulkContacts,
  notice,
  templates,
  contact,
  text,
  name,
  language,
  category,
  body,
  template,
  creating,
  parameterValues,
  parameterKeys,
  selectedTemplate,
  execute,
  run,
  enqueue,
}) {
  async function createTemplate() {
    await run(async () => {
      await execute(
        editingTemplate.value ? "templates.update" : "templates.create",
        {
          id: editingTemplate.value || undefined,
          name: name.value,
          language: language.value,
          category: category.value,
          components: [{ type: "BODY", text: body.value }],
        },
      );
      notice.value = "Submitted to Meta for review";
      creating.value = false;
      templates.value = (await execute("templates.list")).data || [];
    });
  }

  async function sendTemplate() {
    await run(async () => {
      const t = selectedTemplate.value;
      if (!t || t.status !== "APPROVED")
        throw new Error("Select an approved template");
      await enqueue(
        "templates.send",
        {
          name: t.name,
          language: t.language,
          components: buildTemplateComponents(parameterKeys.value, parameterValues.value),
        },
        bulkContacts.value.length ? bulkContacts.value : [contact.value],
      );
    });
  }

  async function nextTemplates() {
    await run(async () => {
      const r = await execute("templates.list", {
        after: templateCursor.value,
      });
      templates.value = r.data || [];
      templateCursor.value = r.paging?.cursors?.after || "";
      template.value = "";
    });
  }
  return { createTemplate, sendTemplate, nextTemplates };
}
