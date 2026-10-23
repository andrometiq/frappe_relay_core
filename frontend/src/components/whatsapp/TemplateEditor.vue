<script setup>
import { computed, ref, watch } from "vue";
import { Button, ErrorMessage, FormControl } from "@relay/ui";
import FrappeFormSection from "../frappe/FrappeFormSection.vue";
import FrappeFormView from "../frappe/FrappeFormView.vue";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import {
  TEMPLATE_BUTTON_TYPES,
  addTemplateButton,
  templateForm,
  templateRequest,
  templateSampleFields,
} from "../../services/templateAuthoring";
import TemplateLanguageField from "./TemplateLanguageField.vue";

const props = defineProps({ template: Object, enabled: Boolean });
const emit = defineEmits(["saved", "cancel"]);
const form = ref(
  templateForm({
    ...props.template,
    account_name: "current-account",
    template_name: props.template?.name || "",
    language_code: props.template?.language || "en_US",
  }),
);
const busy = ref(false);
const error = ref("");
const sampleName = ref("");
const samples = computed(() => templateSampleFields(form.value));
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
    if (
      !file.size ||
      file.size > 4 * 1024 * 1024 ||
      !sampleAccept.value.split(",").includes(file.type)
    )
      throw Error("Choose a matching JPEG, PNG, MP4 or PDF file up to 4 MiB.");
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
    <FrappeFormView
      :title="template?.id ? template.name : 'New message template'"
      :breadcrumbs="['Templates', template?.id ? template.name : 'New']"
      :status="template?.status"
      @back="emit('cancel')"
    >
      <template #actions>
        <Button label="Cancel" :disabled="busy" @click="emit('cancel')" />
        <Button :label="template?.id ? 'Submit changes' : 'Submit for review'" type="submit" variant="solid" :loading="busy" :disabled="!enabled" />
      </template>

      <ErrorMessage :message="error" />
      <FrappeFormSection>
        <div class="frappe-field-grid">
          <FormControl label="Template name" v-model="form.template_name" :disabled="busy || !!template?.id" required />
          <TemplateLanguageField v-model="form.language_code" :disabled="busy || !!template?.id" />
          <RelaySelect label="Category" v-model="form.category" :options="['UTILITY', 'MARKETING', 'AUTHENTICATION']" :disabled="busy || !!template?.id" />
          <RelaySelect label="Parameters" v-model="form.parameter_format" :options="[{ value: 'POSITIONAL', label: 'Numbered: {{1}}' }, { value: 'NAMED', label: 'Named: {{customer_name}}' }]" :disabled="busy || !!template?.id" />
        </div>
      </FrappeFormSection>

      <FrappeFormSection title="Message content" description="Compose the message Meta will review.">
        <div class="frappe-field-grid">
          <RelaySelect label="Header" v-model="form.header_type" :options="['NONE', 'TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT', 'LOCATION']" :disabled="busy" />
          <FormControl v-if="form.header_type === 'TEXT'" label="Header text" v-model="form.header_text" :disabled="busy" />
          <div v-if="['IMAGE', 'VIDEO', 'DOCUMENT'].includes(form.header_type)" class="frappe-file-field">
            <label>Header sample<input type="file" :accept="sampleAccept" :disabled="busy || !enabled" @change="uploadSample" /></label>
            <small>Matching file type, up to 4 MiB. Do not include customer information.</small>
            <p v-if="sampleName" role="status">Uploaded: {{ sampleName }}</p>
          </div>
          <div v-if="['IMAGE', 'VIDEO', 'DOCUMENT'].includes(form.header_type)" class="frappe-field-advanced">
            <details><summary>Use an existing sample handle</summary><FormControl label="Sample media handle" v-model="form.header_media_example" :disabled="busy" /></details>
          </div>
          <FormControl class="frappe-grid-wide" label="Message body" type="textarea" :rows="6" v-model="form.body_text" :disabled="busy" required />
          <FormControl class="frappe-grid-wide" label="Footer" v-model="form.footer_text" :disabled="busy" />
        </div>
      </FrappeFormSection>

      <FrappeFormSection v-if="form.category === 'AUTHENTICATION'" title="Authentication" collapsible>
        <div class="frappe-field-grid">
          <FormControl type="checkbox" label="Include security recommendation" v-model="form.add_security_recommendation" :disabled="busy" />
          <FormControl type="number" label="Code expiration (minutes)" v-model="form.code_expiration_minutes" :disabled="busy" />
        </div>
      </FrappeFormSection>

      <FrappeFormSection v-if="samples.length" title="Review examples" description="Examples help Meta validate every variable." collapsible>
        <div class="frappe-field-grid">
          <FormControl v-for="field in samples" :key="field.key" :label="field.label" v-model="form.sample_values[field.scope][field.name]" :disabled="busy" />
        </div>
      </FrappeFormSection>

      <FrappeFormSection title="Buttons" description="Optional actions displayed below the message." collapsible>
        <div class="template-editor-buttons">
          <article v-for="(button, index) in form.buttons" :key="button._client_key" class="template-editor-button">
            <header><strong>Button {{ index + 1 }}</strong><Button icon="trash" variant="ghost" :aria-label="`Remove button ${index + 1}`" :disabled="busy" @click="form.buttons.splice(index, 1)" /></header>
            <div class="frappe-field-grid">
              <RelaySelect label="Action" v-model="button.type" :options="TEMPLATE_BUTTON_TYPES" :disabled="busy" />
              <FormControl label="Button text" v-model="button.text" :disabled="busy" />
              <FormControl v-if="button.type === 'URL'" label="Website URL" v-model="button.url" :disabled="busy" />
              <FormControl v-if="button.type === 'URL'" label="Example URL value" v-model="button.example_value" :disabled="busy" />
              <FormControl v-if="button.type === 'PHONE_NUMBER'" label="Phone number" v-model="button.phone_number" :disabled="busy" />
              <FormControl v-if="button.type === 'COPY_CODE'" label="Example offer code" v-model="button.example_value" :disabled="busy" />
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
          <Button label="Add button" icon-left="plus" :disabled="busy || form.buttons.length >= 10" @click="addTemplateButton(form)" />
        </div>
      </FrappeFormSection>

      <FrappeFormSection title="Delivery settings" collapsible collapsed>
        <div class="frappe-field-grid">
          <FormControl label="Message validity (seconds, optional)" type="number" v-model="form.message_send_ttl_seconds" :disabled="busy" />
          <p v-if="form.advanced_component_count" class="template-advanced-note">{{ form.advanced_component_count }} advanced components will be preserved.</p>
        </div>
      </FrappeFormSection>

      <template #sidebar>
        <section class="template-side-preview">
          <h3>Preview</h3>
          <div class="template-phone-preview">
            <div class="template-preview-bubble">
              <strong v-if="form.header_type === 'TEXT'">{{ form.header_text }}</strong>
              <p>{{ form.body_text || "Your message preview" }}</p>
              <small v-if="form.footer_text">{{ form.footer_text }}</small>
              <div v-if="form.buttons.length" class="template-preview-buttons"><span v-for="button in form.buttons" :key="button._client_key">{{ button.text || button.type }}</span></div>
              <time>12:00</time>
            </div>
          </div>
          <p class="template-preview-note">Preview uses your current unsaved values.</p>
        </section>
      </template>
    </FrappeFormView>
  </form>
</template>
