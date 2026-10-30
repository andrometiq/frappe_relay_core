<script setup>
import { campaignError } from '../../services/campaignErrors.js';
import { computed, inject, ref, useId } from 'vue';
import { Button, ErrorMessage } from '@relay/ui';
import { attachmentSelectionError } from '../../services/campaignMedia';
import { headerChannelKind } from '../../services/templateMedia';
import { attachmentMaxBytes, sizeLabel } from '../messages/attachmentFormats';

const props = defineProps({ modelValue: Object, upload: Function, busy: Boolean, media: String });
const emit = defineEmits(['update:modelValue', 'uploading']);
const uploading = ref(false), error = ref('');
const group = useId();
const capabilities = inject('relayCapabilities', ref({}));
const limit = computed(() => attachmentMaxBytes(capabilities.value, 'WhatsApp', headerChannelKind(props.media)));
const mode = computed(() => props.modelValue?.mode || 'static');
const files = computed(() => props.modelValue?.files || []);
function chooseMode(value) {
  error.value = '';
  emit('update:modelValue', { mode: value, files: [] });
}
async function chooseFiles(event) {
  const selected = Array.from(event.target.files || []);
  event.target.value = '';
  if (!selected.length) return;
  error.value = attachmentSelectionError(selected, mode.value, limit.value);
  if (error.value) return;
  uploading.value = true;
  emit('uploading', true);
  const uploaded = mode.value === 'dynamic' ? [...files.value] : [];
  try {
    for (const file of selected) {
      const file_url = await props.upload(file);
      if (!file_url) throw Error(`Could not upload ${file.name}. Try again.`);
      uploaded.push({ file_url, filename: file.name });
      emit('update:modelValue', { mode: mode.value, files: [...uploaded] });
    }
  } catch (e) { error.value = campaignError(e); }
  finally { uploading.value = false; emit('uploading', false); }
}
</script>

<template>
  <fieldset class="header-files" :disabled="busy || uploading">
    <legend>{{ media }} header attachment</legend>
    <div class="header-modes">
      <label><input type="radio" :name="group" :checked="mode === 'static'" @change="chooseMode('static')" /> Same file for everyone</label>
      <label><input type="radio" :name="group" :checked="mode === 'dynamic'" @change="chooseMode('dynamic')" /> Different file per contact (named by mobile number)</label>
    </div>
    <label class="header-picker"><span>{{ uploading ? 'Uploading…' : mode === 'static' ? 'Choose header file' : 'Add contact files' }}</span>
      <input type="file" :multiple="mode === 'dynamic'" :aria-label="mode === 'static' ? 'Header attachment' : 'Contact header attachments'" @change="chooseFiles" />
    </label>
    <p>Private files<template v-if="limit">, up to {{ sizeLabel(limit) }} each</template>. Use {{ media === 'image' ? 'JPG or PNG' : media === 'video' ? 'MP4' : 'a WhatsApp-supported document' }}.</p>
    <p v-if="mode === 'dynamic'">Name files by mobile number, with or without the country code; spaces are allowed. For example, 98765 43210.{{ media === 'image' ? 'jpg' : media === 'video' ? 'mp4' : 'pdf' }}. Numbers without a country code use the sending company's country. Missing, duplicate and wrong-type attachments are excluded in the preview.</p>
    <div v-if="files.length" class="header-selected" role="status">
      <span>{{ mode === 'static' ? files[0].filename : `${files.length} files selected` }}</span>
      <Button label="Clear files" variant="outline" :disabled="busy || uploading" @click="chooseMode(mode)" />
    </div>
    <ErrorMessage v-if="error" :message="error" />
  </fieldset>
</template>

<style scoped>
.header-files { display: grid; gap: 10px; min-width: 0; padding: 12px; border: 1px solid var(--outline-gray-2); border-radius: 8px; }
.header-files legend { padding: 0 4px; font-size: 13px; color: var(--ink-gray-8); text-transform: capitalize; }
.header-modes { display: grid; gap: 8px; }
.header-modes label { display: flex; align-items: center; gap: 8px; min-height: 44px; font-size: 13px; color: var(--ink-gray-8); }
.header-picker { display: grid; gap: 8px; font-size: 13px; color: var(--ink-gray-8); }
.header-picker input { max-width: 100%; min-height: 44px; }
.header-files p { font-size: 13px; color: var(--ink-gray-6); }
.header-selected { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 13px; overflow-wrap: anywhere; }
</style>
