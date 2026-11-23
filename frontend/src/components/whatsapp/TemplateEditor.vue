<script setup>
import { computed, inject, ref, watch } from "vue";
import { Button, Dialog, ErrorMessage, FormControl, toast } from "@relay/ui";
import SidePanel from "../shell/SidePanel.vue";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import { sentenceCase } from "../../services/textCase";
import { headerChannelKind } from "../../services/templateMedia";
import { attachmentMaxBytes, sizeError, sizeLabel } from "../messages/attachmentFormats";
import {
  TEMPLATE_BUTTON_TYPES,
  addTemplateButton,
  templateForm,
  templateIssues,
  templatePreview,
  templateRequest,
  templateSampleFields,
} from "../../services/templateAuthoring";
import TemplateLanguageField from "./TemplateLanguageField.vue";
import TemplatePreview from "./TemplatePreview.vue";

const props = defineProps({ template: Object, enabled: Boolean });
const emit = defineEmits(["saved", "cancel"]);
const form = ref(
  templateForm({
    ...props.template,
    account_name: "current-account",
    template_name: props.template?.name || "",
    language_code: props.template?.language || "en_US",
    parameter_format: props.template ? props.template.parameter_format : "NAMED",
  }),
);
const attempted = ref(false);
const issues = computed(() => templateIssues(form.value));
const preview = computed(() => templatePreview(form.value));
const headerTypes = computed(() => ["NONE", "TEXT", "IMAGE", "VIDEO", "DOCUMENT", ...(form.value.header_type === "LOCATION" ? ["LOCATION"] : [])]
  .map((value) => ({ value, label: value === "NONE" ? "No header" : sentenceCase(value) })));
// Leaving with unsaved changes asks first.
const initial = JSON.stringify(form.value);
const discarding = ref(false);
function leave() { if (JSON.stringify(form.value) === initial) emit("cancel"); else discarding.value = true; }
const variableHint = computed(() => `Add variables like ${form.value.parameter_format === "NAMED" ? "{{customer_name}}" : "{{1}}"} with text before and after them.`);
function addButton() {
  addTemplateButton(form.value);
  form.value.buttons.at(-1).type = buttonTypes.value[0].value;
}
const buttonTypes = computed(() => {
  const allowed = form.value.category === "AUTHENTICATION" ? ["OTP"]
    : ["QUICK_REPLY", "URL", "PHONE_NUMBER", ...(form.value.category === "MARKETING" ? ["COPY_CODE"] : [])];
  const current = new Set(form.value.buttons.map((button) => button.type));
  return TEMPLATE_BUTTON_TYPES.filter((option) => allowed.includes(option.value) || current.has(option.value));
});
const busy = ref(false);
const error = ref("");
const sampleName = ref("");
const samples = computed(() => templateSampleFields(form.value));
const headerFileHint = { IMAGE: "JPEG or PNG", VIDEO: "MP4", DOCUMENT: "PDF" };
const capabilities = inject("relayCapabilities", ref({}));
const sampleLimit = computed(() => attachmentMaxBytes(capabilities.value, "WhatsApp", headerChannelKind(String(form.value.header_type).toLowerCase())));
const sampleAccept = computed(
  () =>
    ({
      IMAGE: "image/jpeg,image/png",
      VIDEO: "video/mp4",
      DOCUMENT: "application/pdf",
    })[form.value.header_type] || "",
);

watch(
  () => form.value.header_type,
  () => {
    form.value.header_media_example = "";
    sampleName.value = "";
  },
);

async function uploadSample(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || busy.value || !props.enabled) return;
  busy.value = true;
  error.value = "";
  try {
    if (!sampleAccept.value.split(",").includes(file.type))
      throw Error(`Choose a ${headerFileHint[form.value.header_type]} file.`);
    const sizeIssue = sizeError(file.size, sampleLimit.value);
    if (sizeIssue) throw Error(sizeIssue);
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(Error("Could not read this file."));
      reader.readAsDataURL(file);
    });
    const result = await coreApi(
      "whatsapp.execute",
      {
        operation: "templates.media_upload",
        arguments: {
          media_type: form.value.header_type.toLowerCase(),
          filename: file.name,
          mime_type: file.type,
          content_base64: content,
        },
      },
      true,
    );
    if (!result.handle) throw Error("The upload did not return a sample handle.");
    form.value.header_media_example = result.handle;
    sampleName.value = file.name;
  } catch (exception) {
    error.value = exception.message;
  } finally {
    busy.value = false;
  }
}

async function save() {
  if (!props.enabled || busy.value) return;
  attempted.value = true;
  if (issues.value.length) return;
  busy.value = true;
  error.value = "";
  try {
    const { template } = templateRequest(form.value, { submit: true });
    const arguments_ = {
      name: template.template_name,
      language: template.language_code,
      category: template.category,
      parameter_format: template.parameter_format,
      components: template.components,
      ...(template.message_send_ttl_seconds
        ? { message_send_ttl_seconds: template.message_send_ttl_seconds }
        : {}),
      ...(props.template?.id ? { id: props.template.id } : {}),
    };
    await coreApi(
      "whatsapp.execute",
      {
        operation: props.template?.id ? "templates.update" : "templates.create",
        arguments: arguments_,
      },
      true,
    );
    toast(props.template?.id ? "Changes sent to Meta for approval" : "Template sent to Meta for approval");
    emit("saved");
  } catch (exception) {
    error.value = exception.message;
  } finally {
    busy.value = false;
  }
}
</script>


<template>
  <form class="template-editor" @submit.prevent="save">
    <SidePanel wide :title="template?.id ? 'Edit ' + template.name : 'New message template'" label="Template editor" @close="leave">
      <Dialog v-model="discarding" :options="{ title: 'Discard changes?', size: 'sm' }">
        <p>Your changes to this template are not saved.</p>
        <template #actions>
          <Button variant="outline" label="Keep editing" autofocus @click="discarding = false" />
          <Button variant="solid" theme="red" label="Discard" @click="discarding = false; emit('cancel')" />
        </template>
      </Dialog>
      <div class="template-editor-grid">
        <div class="template-editor-form">
          <ErrorMessage :message="error" />
          <section v-if="attempted && issues.length" class="template-issues" role="alert" aria-label="Fix before submitting">
            <strong>Fix before submitting</strong>
            <ul><li v-for="issue in issues" :key="issue">{{ issue }}</li></ul>
          </section>

          <section class="template-editor-section" aria-label="Template details">
            <div>
              <FormControl label="Template name" :model-value="form.template_name" placeholder="order_update" :disabled="busy || !!template?.id" required @update:model-value="value => form.template_name = String(value).toLowerCase().replace(/\s+/g, '_')" />
              <small class="template-field-hint">Use lowercase letters, numbers and underscores. Spaces become underscores.</small>
            </div>
            <TemplateLanguageField v-model="form.language_code" :disabled="busy || !!template?.id" />
            <div class="panel-field">
              <h3 id="template-category-label">Category</h3>
              <div class="segmented" role="group" aria-labelledby="template-category-label">
                <button v-for="option in [{ value: 'UTILITY', label: 'Utility' }, { value: 'MARKETING', label: 'Marketing' }, { value: 'AUTHENTICATION', label: 'Authentication' }]" :key="option.value"
                  type="button" :aria-pressed="form.category === option.value" :disabled="busy || !!template?.id" @click="form.category = option.value">{{ option.label }}</button>
              </div>
            </div>
            <div>
              <RelaySelect label="How to write variables" v-model="form.parameter_format" :options="[{ value: 'NAMED', label: 'Names, like {{customer_name}}' }, { value: 'POSITIONAL', label: 'Numbers, like {{1}}' }]" :disabled="busy || !!template?.id" />
              <small class="template-field-hint" v-text="'Variables are filled in for each person when you send, for example: Hi ' + (form.parameter_format === 'NAMED' ? '{{customer_name}}' : '{{1}}') + '.'" />
            </div>
          </section>

          <section class="template-editor-section" aria-label="Message content">
            <header><h3>Message content</h3><p>Meta reviews this message before you can send it. This usually takes under a day.</p></header>
            <RelaySelect label="Header" v-model="form.header_type" :options="headerTypes" :disabled="busy" />
            <FormControl v-if="form.header_type === 'TEXT'" label="Header text" v-model="form.header_text" maxlength="60" :disabled="busy" />
            <div v-if="['IMAGE', 'VIDEO', 'DOCUMENT'].includes(form.header_type)" class="frappe-file-field">
              <label>Header sample<input type="file" :accept="sampleAccept" :disabled="busy || !enabled" @change="uploadSample" /></label>
              <small>{{ headerFileHint[form.header_type] }} file<template v-if="sampleLimit">, up to {{ sizeLabel(sampleLimit) }}</template>. Do not include customer information.</small>
              <p v-if="sampleName || form.header_media_example" role="status">{{ sampleName ? `Uploaded: ${sampleName}` : "A sample is attached." }}</p>
            </div>
            <FormControl label="Message body" type="textarea" :rows="6" v-model="form.body_text" :disabled="busy" maxlength="1024" required />
            <p class="template-field-hint">{{ variableHint }} {{ form.body_text.length }} / 1024</p>
            <div>
              <FormControl label="Footer (optional)" v-model="form.footer_text" maxlength="60" :disabled="busy" />
              <small class="template-field-hint">Short text under the message. Variables are not allowed here.</small>
            </div>
          </section>

          <section v-if="form.category === 'AUTHENTICATION'" class="template-editor-section" aria-label="Authentication">
            <header><h3>Authentication</h3></header>
            <FormControl type="checkbox" label="Include security recommendation" v-model="form.add_security_recommendation" :disabled="busy" />
            <FormControl type="number" label="Code expiration (minutes)" v-model="form.code_expiration_minutes" :disabled="busy" />
          </section>

          <section v-if="samples.length" class="template-editor-section" aria-label="Review examples">
            <header><h3>Review examples</h3><p>Examples help Meta validate every variable.</p></header>
            <FormControl v-for="field in samples" :key="field.key" :label="field.label" v-model="form.sample_values[field.scope][field.name]" :disabled="busy" />
          </section>

          <section class="template-editor-section" aria-label="Buttons">
            <header><h3>Buttons</h3><p>Optional actions displayed below the message.</p></header>
            <article v-for="(button, index) in form.buttons" :key="button._client_key" class="template-editor-button">
              <header><strong>Button {{ index + 1 }}</strong><Button icon="trash" variant="ghost" :aria-label="`Remove button ${index + 1}`" :disabled="busy" @click="form.buttons.splice(index, 1)" /></header>
              <div class="template-editor-fields">
                <RelaySelect label="Action" v-model="button.type" :options="buttonTypes" :disabled="busy" />
                <FormControl v-if="button.type !== 'COPY_CODE'" label="Button text" v-model="button.text" maxlength="25" :disabled="busy" />
                <FormControl v-if="button.type === 'URL'" label="Website URL" v-model="button.url" placeholder="https://example.com/orders/{{1}}" :disabled="busy" />
                <FormControl v-if="button.type === 'URL'" label="Example URL value" v-model="button.example_value" :disabled="busy" />
                <FormControl v-if="button.type === 'PHONE_NUMBER'" label="Phone number" v-model="button.phone_number" :disabled="busy" />
                <FormControl v-if="button.type === 'COPY_CODE'" label="Example offer code" v-model="button.example_value" maxlength="20" :disabled="busy" />
                <RelaySelect v-if="button.type === 'OTP'" label="OTP delivery" v-model="button.otp_type" :options="['COPY_CODE', 'ONE_TAP', 'ZERO_TAP']" :disabled="busy" />
                <FormControl v-if="button.type === 'OTP' && button.otp_type !== 'COPY_CODE'" label="Autofill text" v-model="button.autofill_text" :disabled="busy" />
                <FormControl v-if="button.type === 'OTP' && button.otp_type === 'ZERO_TAP'" label="Android package name" v-model="button.package_name" :disabled="busy" />
                <FormControl v-if="button.type === 'OTP' && button.otp_type === 'ZERO_TAP'" label="App signature hash" v-model="button.signature_hash" :disabled="busy" />
                <FormControl v-if="button.type === 'FLOW'" label="WhatsApp Flow ID" v-model="button.flow_id" :disabled="busy" />
                <RelaySelect v-if="button.type === 'FLOW'" label="Flow action" v-model="button.flow_action" :options="['navigate', 'data_exchange']" :disabled="busy" />
                <FormControl v-if="button.type === 'FLOW' && button.flow_action === 'navigate'" label="Opening screen" v-model="button.navigate_screen" :disabled="busy" />
                <FormControl v-if="button.type === 'CATALOG'" label="Product thumbnail retailer ID" v-model="button.thumbnail_product_retailer_id" :disabled="busy" />
                <FormControl v-if="button.type === 'VOICE_CALL'" label="Call request validity (minutes)" type="number" v-model="button.ttl_minutes" :disabled="busy" />
              </div>
            </article>
            <small v-if="form.buttons.length > 1" class="template-field-hint">Quick replies are sent together, before or after the other buttons, as Meta requires. The preview shows the sent order.</small>
            <Button variant="outline" label="Add button" icon-left="plus" :disabled="busy || form.buttons.length >= 10" @click="addButton" />
          </section>

          <details class="template-editor-section template-editor-delivery">
            <summary>Delivery settings</summary>
            <FormControl label="Message validity (seconds, optional)" type="number" v-model="form.message_send_ttl_seconds" :disabled="busy" />
            <p v-if="form.advanced_component_count" class="template-advanced-note">{{ form.advanced_component_count }} advanced components will be preserved.</p>
          </details>
        </div>
        <TemplatePreview class="template-editor-preview" :preview="preview" note="Preview uses your current unsaved values and examples." />
      </div>
      <template #footer>
        <Button :label="template?.id ? 'Send changes to Meta' : 'Send to Meta for approval'" type="submit" variant="solid" :loading="busy" :disabled="!enabled || (attempted && issues.length > 0)" />
        <Button variant="outline" label="Cancel" :disabled="busy" @click="leave" />
      </template>
    </SidePanel>
  </form>
</template>

<style scoped>
.template-editor { display:contents; }
.template-editor-grid { display:grid; grid-template-columns:minmax(0,1fr) 290px; gap:20px; align-items:start; }
.template-editor-form { display:flex; flex-direction:column; gap:16px; min-width:0; }
.template-editor-section { display:flex; flex-direction:column; gap:12px; padding-bottom:16px; border-bottom:1px solid var(--relay-stroke); }
.template-editor-section > header h3 { color:var(--relay-ink); font-size:13.5px; font-weight:600; }
.template-editor-section > header p { margin-top:2px; color:var(--relay-ink-3); font-size:12.5px; }
.template-editor-section :deep(.template-field-hint) { margin-top:4px; display:block; }
.template-editor-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.template-editor-delivery summary { cursor:pointer; color:var(--relay-ink-2); font-size:13px; font-weight:500; }
.template-editor-preview { position:sticky; top:0; }
.template-issues { margin:0; }
@media (max-width:1180px) { .template-editor-grid { grid-template-columns:minmax(0,1fr); } .template-editor-preview { position:static; } }
@media (max-width:768px) { .template-editor-fields { grid-template-columns:1fr; } }
</style>
