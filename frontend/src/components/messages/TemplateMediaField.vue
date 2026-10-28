<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from "vue";
import { Button, ErrorMessage, FeatherIcon, TextInput } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import { formatBytes } from "../../services/mediaCache";
import { headerChannelKind, headerFileError, headerLinkError, linkFileName, readBase64 } from "../../services/templateMedia";
import { attachmentAccept } from "./attachmentFormats";

// The header file of a template send. `modelValue` is {id, filename, size} after an upload or {link, filename} for a link.
const props = defineProps({ modelValue: Object, field: Object, channel: String, disabled: Boolean });
const emit = defineEmits(["update:modelValue"]);
const capabilities = inject("relayCapabilities", ref({}));
const format = computed(() => props.field.parameterType);
const source = ref(props.modelValue?.link ? "link" : "upload");
const link = ref(props.modelValue?.link || "");
const localPreview = ref(""), busy = ref(false), error = ref(""), dragging = ref(false), previewFailed = ref(false);
const picker = ref(null);
const accept = computed(() => attachmentAccept(capabilities.value, "WhatsApp", headerChannelKind(format.value)));
const hint = computed(() => (accept.value ? accept.value.split(",").map((row) => row.slice(1).toUpperCase()).join(", ") + " · " : "") + "up to 4 MB");
const linkError = computed(() => (link.value.trim() ? headerLinkError(link.value) : ""));
const value = computed(() => props.modelValue || null);
const previewSource = computed(() => value.value?.link || localPreview.value);
const fileName = computed(() => value.value?.filename || (value.value?.link ? linkFileName(value.value.link) : "Uploaded file"));
const detail = computed(() => value.value?.link ? new URL(value.value.link).hostname : formatBytes(value.value?.size));
const icon = computed(() => ({ image: "image", video: "video", document: "file-text" })[format.value]);

function clearPreview() {
  if (localPreview.value) URL.revokeObjectURL(localPreview.value);
  localPreview.value = "";
  previewFailed.value = false;
}
function choose(next) {
  if (props.disabled || busy.value || source.value === next) return;
  source.value = next;
  remove();
}
function remove() {
  clearPreview();
  link.value = "";
  error.value = "";
  emit("update:modelValue", null);
}
async function upload(file) {
  if (!file || props.disabled || busy.value) return;
  error.value = headerFileError(capabilities.value, format.value, file);
  if (error.value) return;
  busy.value = true;
  try {
    const result = await coreApi("template_media.upload", {
      channel: props.channel, media_type: format.value, filename: file.name, content_base64: await readBase64(file),
    }, true);
    clearPreview();
    if (format.value !== "document") localPreview.value = URL.createObjectURL(file);
    emit("update:modelValue", { id: result.id, filename: result.filename, size: result.size });
  } catch (exception) {
    error.value = exception.message;
  } finally {
    busy.value = false;
  }
}
function picked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  upload(file);
}
function dropped(event) {
  dragging.value = false;
  upload(event.dataTransfer?.files?.[0]);
}
watch(link, (next) => {
  if (source.value !== "link") return;
  previewFailed.value = false;
  const text = next.trim();
  emit("update:modelValue", text && !headerLinkError(text)
    ? { link: text, ...(format.value === "document" ? { filename: linkFileName(text) } : {}) } : null);
});
// A restored draft brings its link back, and the card rebuilds the thumbnail from it.
watch(() => props.modelValue?.link, (saved) => {
  if (!saved || saved === link.value.trim()) return;
  source.value = "link";
  link.value = saved;
});
onBeforeUnmount(clearPreview);
</script>

<template>
  <div class="relay-field template-media-field">
    <span class="relay-field__label">{{ field.label }}</span>
    <div class="template-media-tabs" role="tablist" :aria-label="field.label + ' source'">
      <Button label="Upload file" icon-left="upload" role="tab" size="sm" :aria-selected="source === 'upload'"
        :variant="source === 'upload' ? 'subtle' : 'ghost'" :disabled="disabled || busy" @click="choose('upload')" />
      <Button label="Use a link" icon-left="link" role="tab" size="sm" :aria-selected="source === 'link'"
        :variant="source === 'link' ? 'subtle' : 'ghost'" :disabled="disabled || busy" @click="choose('link')" />
    </div>
    <div v-if="value" class="template-media-card" :aria-label="'Chosen ' + format">
      <span class="template-media-thumb">
        <img v-if="format === 'image' && previewSource && !previewFailed" :src="previewSource" :alt="fileName"
          referrerpolicy="no-referrer" @error="previewFailed = true" />
        <video v-else-if="format === 'video' && localPreview" :src="localPreview" muted preload="metadata" />
        <FeatherIcon v-else :name="icon" class="h-5 w-5" />
      </span>
      <span class="template-media-copy">
        <strong :title="fileName">{{ fileName }}</strong>
        <small>{{ detail }}<template v-if="previewFailed"> · Preview unavailable</template></small>
      </span>
      <Button icon="x" variant="ghost" :aria-label="'Remove ' + format" :disabled="disabled" @click="remove" />
    </div>
    <div v-else-if="source === 'upload'" class="template-media-drop" :class="{ dragging }"
      @dragover.prevent="dragging = !disabled" @dragleave="dragging = false" @drop.prevent="dropped">
      <FeatherIcon :name="icon" class="h-5 w-5 text-ink-gray-5" />
      <span>Drop {{ format === 'image' ? 'an' : 'a' }} {{ format }} here or</span>
      <Button label="Choose file" :loading="busy" :disabled="disabled || !channel" @click="picker.click()" />
      <small>{{ hint }}</small>
      <input ref="picker" type="file" class="sr-only" :accept="accept" :aria-label="'Upload ' + format" @change="picked" />
    </div>
    <template v-else>
      <TextInput v-model="link" type="url" inputmode="url" placeholder="https://example.com/file" :disabled="disabled"
        :aria-label="field.label + ' link'" />
      <small v-if="!linkError" class="text-ink-gray-5">A public https link. WhatsApp downloads the file from it.</small>
    </template>
    <ErrorMessage :message="error || linkError" />
  </div>
</template>

<style scoped>
.template-media-tabs { display: flex; gap: 4px; }
.template-media-drop {
  display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 16px; text-align: center;
  border: 1px dashed var(--relay-stroke-strong); border-radius: 8px; background: var(--relay-layer);
  transition: border-color var(--relay-fast) var(--relay-ease), background var(--relay-fast) var(--relay-ease);
}
.template-media-drop.dragging { border-color: var(--relay-accent); background: var(--relay-accent-soft); }
.template-media-drop small, .template-media-copy small { color: var(--relay-ink-3); font-size: 12px; }
.template-media-card {
  display: flex; align-items: center; gap: 10px; padding: 8px; min-width: 0;
  border: 1px solid var(--relay-stroke); border-radius: 8px; background: var(--relay-layer);
}
.template-media-thumb {
  display: grid; flex: none; place-items: center; width: 56px; height: 56px; overflow: hidden;
  border-radius: 6px; background: var(--relay-hover); color: var(--relay-ink-2);
}
.template-media-thumb img, .template-media-thumb video { width: 100%; height: 100%; object-fit: cover; }
.template-media-copy { display: flex; flex: 1; min-width: 0; flex-direction: column; }
.template-media-copy strong { overflow: hidden; color: var(--relay-ink); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
</style>
