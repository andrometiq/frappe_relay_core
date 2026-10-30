<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { FeatherIcon } from "@relay/ui";
import { loadMedia, formatBytes } from "../services/mediaCache";
import { documentType } from "./messageContent";
const props = defineProps({ message: Object, data: Object });
const frame = ref(null), lightbox = ref(null);
const media = ref(null), error = ref(null), loading = ref(false);
const kind = computed(() =>
  ["photo", "image"].includes(props.data.kind) ? "image"
    : ["video", "animation"].includes(props.data.kind) ? "video"
      : ["audio", "voice"].includes(props.data.kind) ? "audio" : "document");
const filename = computed(() => props.data.media?.file_name || props.data.media?.filename || "");
const audioLabel = computed(() => props.data.kind === "voice" || props.data.media?.voice ? "Voice message" : "Audio");
const size = computed(() => formatBytes(media.value?.size || props.data.media?.file_size));
let generation = 0, visibility;

async function load() {
  if (loading.value || media.value || props.message._pending) return media.value;
  const current = ++generation;
  loading.value = true; error.value = null;
  try {
    const value = await loadMedia(props.message.name);
    if (current === generation) media.value = value;
  } catch (failure) {
    if (current === generation) error.value = failure;
  } finally {
    if (current === generation) loading.value = false;
  }
  return media.value;
}
// Images and audio load when the bubble nears the screen; video and documents load on request.
function observe() {
  visibility?.disconnect();
  if (!frame.value || !["image", "audio"].includes(kind.value)) return;
  visibility = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return;
    visibility.disconnect();
    load();
  }, { rootMargin: "300px 0px" });
  visibility.observe(frame.value);
}
async function save() {
  const value = await load();
  if (!value) return;
  const link = Object.assign(document.createElement("a"), { href: value.url, download: filename.value || "attachment" });
  document.body.appendChild(link); link.click(); link.remove();
}
onMounted(observe);
onBeforeUnmount(() => { ++generation; visibility?.disconnect(); });
watch(() => props.message.name, () => {
  ++generation; media.value = null; error.value = null; loading.value = false;
  observe();
});
</script>
<template>
  <div class="message-media" :data-media-kind="kind">
    <div v-if="kind === 'image'" ref="frame" class="media-frame">
      <button v-if="media && !error" type="button" class="media-fill" :aria-label="'Open ' + (data.caption || 'photo')" @click="lightbox.showModal()">
        <img :src="media.url" :alt="data.caption || 'Photo'" class="media-fill" @error="error = { message: 'This photo cannot be shown.', retry: false }" />
      </button>
      <span v-else class="media-placeholder" role="status"><FeatherIcon :name="loading ? 'loader-circle' : 'image'" :size="22" />{{ loading ? 'Loading photo…' : error ? 'Photo unavailable' : 'Photo' }}</span>
    </div>
    <div v-else-if="kind === 'video'" class="media-frame media-frame-video">
      <video v-if="media && !error" :src="media.url" controls autoplay playsinline class="media-fill" @error="error = { message: 'This video cannot be played here. Download it instead.', retry: false }" />
      <button v-else type="button" class="media-placeholder" :disabled="loading || !!error" @click="load">
        <FeatherIcon :name="loading ? 'loader-circle' : 'play'" :size="26" />{{ loading ? 'Loading video…' : error ? 'Video unavailable' : 'Play video' }}
      </button>
    </div>
    <div v-else-if="kind === 'audio'" ref="frame" class="media-audio">
      <FeatherIcon :name="audioLabel === 'Voice message' ? 'mic' : 'music'" :size="18" />
      <audio v-if="media && !error" :src="media.url" controls preload="metadata" :aria-label="audioLabel"
        @error="error = { message: 'This audio cannot be played here. Download it instead.', retry: false }" />
      <span v-else class="media-audio-pending" role="status">{{ loading ? 'Loading ' + audioLabel.toLowerCase() + '…' : error ? audioLabel + ' unavailable' : audioLabel }}</span>
    </div>
    <div v-else class="media-document">
      <FeatherIcon name="file-text" :size="26" />
      <div class="media-document-text">
        <strong :title="filename">{{ filename || 'Document' }}</strong>
        <span class="media-meta">{{ [documentType(data.media), size].filter(Boolean).join(' · ') }}</span>
      </div>
      <button type="button" class="media-download" :disabled="loading" :aria-label="'Download ' + (filename || 'document')" @click="save">
        <FeatherIcon :name="loading ? 'loader-circle' : 'download'" :size="18" />
      </button>
    </div>
    <p v-if="error" class="media-error" role="alert">
      {{ error.message }}
      <button v-if="error.retry" type="button" @click="load">Retry</button>
      <button v-else-if="media && kind !== 'document'" type="button" @click="save">Download</button>
    </p>
    <p v-if="data.caption" class="whitespace-pre-wrap break-words">{{ data.caption }}</p>
    <Teleport to="body"><dialog v-if="kind === 'image' && media" ref="lightbox" class="media-lightbox" aria-label="Photo" @click.self="lightbox.close()">
      <img :src="media.url" :alt="data.caption || 'Photo'" />
      <div class="media-lightbox-actions">
        <button type="button" @click="save"><FeatherIcon name="download" />Download</button>
        <button type="button" @click="lightbox.close()"><FeatherIcon name="x" />Close</button>
      </div>
    </dialog></Teleport>
  </div>
</template>
