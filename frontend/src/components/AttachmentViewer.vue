<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { FeatherIcon } from "@relay/ui";
import { loadMedia, formatBytes } from "../services/mediaCache";
import { attachmentKind, documentType } from "./messageContent";
// `link` shows a template header sent by https link; `downloadable` is false when no copy can be fetched.
const props = defineProps({ message: Object, data: Object, link: { type: String, default: "" }, downloadable: { type: Boolean, default: true } });
const frame = ref(null), lightbox = ref(null);
const media = ref(null), error = ref(null), loading = ref(false), shown = ref(false);
const kind = computed(() => attachmentKind(props.data.kind));
const filename = computed(() => props.data.media?.file_name || props.data.media?.filename || "");
const audioLabel = computed(() => props.data.kind === "voice" || props.data.media?.voice ? "Voice message" : "Audio");
const label = computed(() => ({ image: "Photo", video: "Video", audio: audioLabel.value, document: "Document" })[kind.value]);
const size = computed(() => formatBytes(media.value?.size || props.data.media?.file_size));
let generation = 0, visibility;

async function load() {
  if (props.link) return (media.value ||= { url: props.link });
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
function fail(message) {
  error.value = { message, retry: false };
}
// Photos, video and audio load when the bubble nears the screen; documents load on request.
function observe() {
  visibility?.disconnect();
  if (!frame.value || kind.value === "document") return;
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
  const target = props.link ? { target: "_blank", rel: "noopener noreferrer" } : { download: filename.value || "attachment" };
  const anchor = Object.assign(document.createElement("a"), { href: value.url, ...target });
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
}
onMounted(observe);
onBeforeUnmount(() => { ++generation; visibility?.disconnect(); });
watch(() => [props.message.name, props.link], () => {
  ++generation; media.value = null; error.value = null; loading.value = false; shown.value = false;
  observe();
});
</script>
<template>
  <div class="message-media" :data-media-kind="kind">
    <div v-if="error" class="media-unavailable" role="alert">
      <FeatherIcon :name="kind === 'document' ? 'file-text' : 'alert-circle'" :size="18" />
      <span class="media-document-text">
        <strong>{{ kind === 'document' ? filename || label : label }} unavailable</strong>
        <span class="media-meta">{{ error.message }}</span>
      </span>
      <button v-if="error.retry" type="button" @click="load">Retry</button>
      <button v-else-if="media && kind !== 'document'" type="button" @click="save">Download</button>
    </div>
    <div v-else-if="kind === 'image' || kind === 'video'" ref="frame" class="media-visual" :class="{ 'is-shown': shown }">
      <span v-if="!shown" class="media-placeholder" role="status">
        <FeatherIcon :name="loading || media ? 'loader-circle' : kind === 'image' ? 'image' : 'video'" :size="22" />
        {{ loading || media ? 'Loading ' + label.toLowerCase() + '…' : label }}
      </span>
      <button v-if="media && kind === 'image'" type="button" class="media-open" :aria-label="'Open ' + (data.caption || 'photo')" @click="lightbox.showModal()">
        <img :src="media.url" :alt="data.caption || 'Photo'" class="media-picture" referrerpolicy="no-referrer"
          @load="shown = true" @error="fail('This photo cannot be shown.')" />
      </button>
      <video v-else-if="media" :src="media.url" controls playsinline preload="metadata" class="media-picture"
        :aria-label="data.caption || 'Video'" @loadedmetadata="shown = true" @error="fail('This video cannot be played here.')" />
    </div>
    <div v-else-if="kind === 'audio'" ref="frame" class="media-audio">
      <FeatherIcon :name="audioLabel === 'Voice message' ? 'mic' : 'music'" :size="18" />
      <audio v-if="media" :src="media.url" controls preload="metadata" :aria-label="audioLabel"
        @error="fail('This audio cannot be played here. Download it instead.')" />
      <span v-else class="media-audio-pending" role="status">{{ loading ? 'Loading ' + audioLabel.toLowerCase() + '…' : audioLabel }}</span>
    </div>
    <div v-else class="media-document">
      <FeatherIcon name="file-text" :size="26" />
      <div class="media-document-text">
        <strong :title="filename">{{ filename || 'Document' }}</strong>
        <span class="media-meta">{{ [documentType(data.media), size].filter(Boolean).join(' · ') }}</span>
      </div>
      <button v-if="downloadable" type="button" class="media-download" :disabled="loading"
        :aria-label="(link ? 'Open ' : 'Download ') + (filename || 'document')" @click="save">
        <FeatherIcon :name="loading ? 'loader-circle' : link ? 'external-link' : 'download'" :size="18" />
      </button>
    </div>
    <p v-if="data.caption" class="whitespace-pre-wrap break-words">{{ data.caption }}</p>
    <Teleport to="body"><dialog v-if="kind === 'image' && media" ref="lightbox" class="media-lightbox" aria-label="Photo" @click.self="lightbox.close()">
      <img :src="media.url" :alt="data.caption || 'Photo'" referrerpolicy="no-referrer" />
      <div class="media-lightbox-actions">
        <button type="button" @click="save"><FeatherIcon name="download" />Download</button>
        <button type="button" @click="lightbox.close()"><FeatherIcon name="x" />Close</button>
      </div>
    </dialog></Teleport>
  </div>
</template>
