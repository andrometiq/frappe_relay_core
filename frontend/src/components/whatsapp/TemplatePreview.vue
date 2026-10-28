<script setup>
import { ref, watch } from "vue";
import { FeatherIcon } from "@relay/ui";
const props = defineProps({ preview: { type: Object, required: true }, note: String });
const imageFailed = ref(false);
watch(() => props.preview.mediaUrl, () => (imageFailed.value = false));
const mediaIcon = { image: "image", video: "film", document: "file-text", location: "map-pin" };
</script>
<template>
  <section class="template-side-preview" aria-label="WhatsApp preview">
    <h3>Preview</h3>
    <div class="template-phone-preview">
      <div class="template-preview-bubble">
        <img v-if="preview.media === 'image' && preview.mediaUrl && !imageFailed" class="template-preview-image" :src="preview.mediaUrl" alt="Image header" referrerpolicy="no-referrer" @error="imageFailed = true" />
        <span v-else-if="preview.media" class="template-preview-media"><FeatherIcon :name="mediaIcon[preview.media]" :size="22" /><small>{{ preview.media }} header</small></span>
        <strong v-if="preview.header">{{ preview.header }}</strong>
        <p style="white-space:pre-wrap">{{ preview.body || "Your message preview" }}</p>
        <small v-if="preview.footer">{{ preview.footer }}</small>
        <time>12:00</time>
        <div v-if="preview.buttons.length" class="template-preview-buttons">
          <span v-for="(button, index) in preview.buttons" :key="button.key || index"><FeatherIcon :name="button.icon" :size="11" />{{ button.text }}</span>
        </div>
      </div>
    </div>
    <p v-if="note" class="template-preview-note">{{ note }}</p>
  </section>
</template>
<style scoped>
.template-preview-image { display:block; width:100%; max-height:180px; object-fit:cover; margin:-3px 0 8px; border-radius:6px; }
.template-preview-media { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; min-height:96px; margin:-3px -4px 8px; border-radius:6px; background:var(--surface-gray-3); color:var(--ink-gray-6); text-transform:capitalize; }
.template-preview-buttons > span { display:flex; align-items:center; justify-content:center; gap:5px; }
.template-preview-bubble { padding-bottom:9px; }
.template-preview-bubble > p { max-height:320px; overflow-y:auto; }
.template-preview-bubble > time { position:static; display:block; margin-top:2px; text-align:right; }
</style>
