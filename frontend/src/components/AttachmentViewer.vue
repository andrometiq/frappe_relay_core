<script setup>
import { computed, ref, watch } from "vue";
import { Button } from "@relay/ui";
const props = defineProps({ message: Object, data: Object });
const opened = ref(false),
  failed = ref(false);
const url = computed(
  () =>
    "/api/method/relay_core.attachments.read?message=" +
    encodeURIComponent(props.message.name),
);
const filename = computed(
  () =>
    props.data.media?.file_name || props.data.media?.filename || "Attachment",
);
const pdf = computed(
  () =>
    props.data.media?.mime_type === "application/pdf" ||
    filename.value.toLowerCase().endsWith(".pdf"),
);
watch(
  () => props.message.name,
  () => {
    opened.value = false;
    failed.value = false;
  },
);
</script>
<template>
  <div class="space-y-2">
    <p class="break-words">{{ filename }}</p>
    <Button
      v-if="!opened"
      label="Open attachment"
      @click="opened = true"
    /><template v-else
      ><img
        v-if="['photo', 'image'].includes(data.kind)"
        :src="url"
        :alt="data.caption || filename"
        class="max-w-full max-h-96 object-contain"
        loading="lazy"
        @error="failed = true" /><video
        v-else-if="['video', 'animation'].includes(data.kind)"
        :src="url"
        controls
        playsinline
        preload="metadata"
        class="max-w-full max-h-96"
        @error="failed = true" /><audio
        v-else-if="['audio', 'voice'].includes(data.kind)"
        :src="url"
        controls
        preload="metadata"
        class="max-w-full"
        @error="failed = true" /><iframe
        v-else-if="pdf"
        :src="url"
        :title="filename"
        sandbox
        class="w-full h-96 border rounded" />
      <p v-if="failed" role="status">
        Preview unavailable. You can try downloading the attachment.
      </p>
      <a
        :href="url + '&download=1'"
        class="underline"
        target="_blank"
        rel="noopener noreferrer"
        >Download attachment</a
      ><Button label="Close attachment" @click="opened = false"
    /></template>
    <p v-if="data.caption" class="whitespace-pre-wrap break-words">
      {{ data.caption }}
    </p>
  </div>
</template>
