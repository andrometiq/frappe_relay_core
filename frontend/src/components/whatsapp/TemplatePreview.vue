<script setup>
import { ref, watch } from "vue";
import { FeatherIcon } from "@relay/ui";
const props = defineProps({ preview: { type: Object, required: true }, note: String });
const imageFailed = ref(false);
watch(() => props.preview.mediaUrl, () => (imageFailed.value = false));
const mediaIcon = { image: "image", video: "film", document: "file-text", location: "map-pin" };
</script>
<template>
  <section class="wa-preview" aria-label="WhatsApp preview">
    <h3>Preview</h3>
    <div class="wa-preview-wall">
      <div class="wa-preview-bubble">
        <img v-if="preview.media === 'image' && preview.mediaUrl && !imageFailed" class="wa-preview-image" :src="preview.mediaUrl" alt="Image header" referrerpolicy="no-referrer" @error="imageFailed = true" />
        <span v-else-if="preview.media" class="wa-preview-media"><FeatherIcon :name="mediaIcon[preview.media]" :size="22" /><small>{{ preview.media }} header</small></span>
        <strong v-if="preview.header">{{ preview.header }}</strong>
        <p>{{ preview.body || "Your message preview" }}</p>
        <span class="wa-preview-meta"><small v-if="preview.footer">{{ preview.footer }}</small><time>12:00</time></span>
      </div>
      <span v-for="(button, index) in preview.buttons" :key="button.key || index" class="wa-preview-button"><FeatherIcon :name="button.icon" :size="13" />{{ button.text }}</span>
    </div>
    <p v-if="note" class="wa-preview-note">{{ note }}</p>
  </section>
</template>
<style scoped>
.wa-preview { display:flex; flex-direction:column; gap:6px; min-width:0; }
.wa-preview > h3 { color:var(--relay-ink-3); font-size:12px; font-weight:500; }
.wa-preview-wall { display:flex; flex-direction:column; gap:3px; width:100%; max-width:300px; margin:0 auto; padding:14px 12px; border:1px solid var(--relay-stroke); border-radius:14px; background:#efe7de; }
.wa-preview-bubble { position:relative; padding:8px 10px 6px; border-radius:8px; background:#fff; color:#111b21; box-shadow:0 1px 1px rgb(0 0 0 / 8%); font-size:12.5px; line-height:1.5; }
.wa-preview-bubble > strong { display:block; margin-bottom:4px; font-size:13px; }
.wa-preview-bubble > p { max-height:320px; overflow-y:auto; white-space:pre-wrap; overflow-wrap:anywhere; }
.wa-preview-meta { display:flex; align-items:flex-end; justify-content:space-between; gap:10px; margin-top:4px; color:#667781; font-size:11px; }
.wa-preview-meta time { margin-left:auto; }
.wa-preview-image { display:block; width:100%; max-height:180px; margin-bottom:8px; object-fit:cover; border-radius:6px; }
.wa-preview-media { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; min-height:96px; margin-bottom:8px; border-radius:6px; background:#e9edef; color:#54656f; text-transform:capitalize; }
.wa-preview-button { display:flex; align-items:center; justify-content:center; gap:5px; padding:7px; border-radius:8px; background:#fff; color:#027eb5; font-size:12.5px; font-weight:500; box-shadow:0 1px 1px rgb(0 0 0 / 8%); }
.wa-preview-note { color:var(--relay-ink-soft); font-size:12px; }
</style>
