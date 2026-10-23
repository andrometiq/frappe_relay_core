<script setup>
import { computed, defineAsyncComponent, ref, watch, inject } from "vue";
import {
  messageData,
  objectValue,
  stickerURL,
  mapURL,
  reactionLabels,
} from "./messageContent";
import {messagesKey} from '../composables/messagesContext';
const chat=inject(messagesKey,null), translationOpen=ref(false);
const translationEnabled=computed(()=>chat?.channels.value.some(row=>row.value===props.message.channel&&row.translation_enabled));
const MessageTranslation=defineAsyncComponent(()=>import('./MessageTranslation.vue'));
const MessageTranscript = defineAsyncComponent(() => import("./MessageTranscript.vue"));
const EmailContent = defineAsyncComponent(() => import("./EmailContent.vue"));
const AttachmentViewer = defineAsyncComponent(
  () => import("./AttachmentViewer.vue"),
);
const TgsSticker = defineAsyncComponent(() => import("./TgsSticker.vue"));
const props = defineProps({ message: { type: Object, required: true }, showReplyReference: { type: Boolean, default: true } });
watch(translationEnabled,value=>{if(!value)translationOpen.value=false});
const data = computed(() => messageData(props.message));
const context = computed(() => objectValue(props.message.provider_context));
const loaded = ref(false),
  mediaError = ref(false);
watch(
  () => props.message.name,
  () => {
    loaded.value = false;
    mediaError.value = false;
  },
);
const source = computed(() => stickerURL(props.message.name));
const animatedDownload = computed(
  () => data.value.media?.is_animated && context.value.provider === "Telegram",
);
const video = computed(
  () =>
    data.value.media?.is_video || data.value.media?.mime_type === "video/webm",
);
</script>

<template>
  <div class="message-content text-sm space-y-2" :data-message-kind="data.kind">
    <div
      v-if="showReplyReference && context.reply_to_message_id"
      class="text-xs text-ink-gray-5 border-l-2 pl-2"
    >
      Reply to {{ context.reply_to_message_id }}
    </div>
    <template v-if="!translationOpen || !['text','email'].includes(data.kind)">
    <EmailContent v-if="data.email" :message="message" :email="data.email" />
    <p v-if="data.kind === 'text'" class="whitespace-pre-wrap break-words">
      {{ data.text }}
    </p>
    <div v-else-if="data.kind === 'sticker'" class="space-y-2">
      <TgsSticker v-if="animatedDownload" :source="source" />
      <button
        v-else-if="!loaded"
        class="rounded border px-3 py-2"
        @click="loaded = true"
      >
        Load sticker
      </button>
      <template v-else-if="!mediaError">
        <video
          v-if="video"
          :src="source"
          controls
          loop
          muted
          playsinline
          preload="metadata"
          class="max-h-48 max-w-full"
          @error="mediaError = true"
        />
        <img
          v-else
          :src="source"
          alt="Sticker"
          loading="lazy"
          class="max-h-48 max-w-full object-contain"
          @error="mediaError = true"
        />
      </template>
      <p v-if="mediaError" role="status">Sticker unavailable.</p>
      <p v-if="data.media?.emoji">{{ data.media.emoji }}</p>
    </div>
    <AttachmentViewer
      v-else-if="
        [
          'photo',
          'image',
          'video',
          'audio',
          'voice',
          'document',
          'animation',
        ].includes(data.kind)
      "
      :message="message"
      :data="data"
    />
    <div v-else-if="data.kind === 'location'" class="space-y-1">
      <strong>{{ data.location?.name || "Location" }}</strong>
      <p v-if="data.location?.address">{{ data.location.address }}</p>
      <p>{{ data.location?.latitude }}, {{ data.location?.longitude }}</p>
      <a
        v-if="mapURL(data.location)"
        :href="mapURL(data.location)"
        target="_blank"
        rel="noopener noreferrer"
        class="underline"
        >Open map</a
      >
    </div>
    <div
      v-else-if="['contact', 'contacts'].includes(data.kind)"
      class="space-y-3"
    >
      <div
        v-for="(card, index) in data.contacts || []"
        :key="index"
        class="rounded border p-3"
      >
        <strong>{{ card.name?.formatted_name || "Contact" }}</strong>
        <p v-for="(phone, i) in card.phones || []" :key="'phone-' + i">
          {{ phone.phone || phone.wa_id }}
        </p>
        <p v-for="(email, i) in card.emails || []" :key="'email-' + i">
          {{ email.email }}
        </p>
        <details
          v-if="
            card.addresses?.length ||
            card.urls?.length ||
            card.org ||
            card.birthday
          "
          class="text-xs"
        >
          <summary>More details</summary>
          <p v-for="(address, i) in card.addresses || []" :key="'address-' + i">
            {{
              [
                address.street,
                address.city,
                address.state,
                address.zip,
                address.country,
              ]
                .filter(Boolean)
                .join(", ")
            }}
          </p>
          <p v-if="card.org">
            {{
              [card.org.company, card.org.department, card.org.title]
                .filter(Boolean)
                .join(" · ")
            }}
          </p>
          <p v-if="card.birthday">{{ card.birthday }}</p>
          <p v-for="(url, i) in card.urls || []" :key="'url-' + i">
            {{ url.url }}
          </p>
        </details>
      </div>
      <details v-if="data.vcard" class="text-xs">
        <summary>Contact card details</summary>
        <pre class="whitespace-pre-wrap break-words">{{ data.vcard }}</pre>
      </details>
    </div>
    <div v-else>
      <p>{{ data.caption || message.content || data.kind }}</p>
      <p v-if="data.media?.file_name || data.media?.filename">
        {{ data.media.file_name || data.media.filename }}
      </p>
    </div>
    </template>
    <MessageTranslation v-if="translationEnabled && ['text','audio','voice'].includes(data.kind) && !message._pending" :message="message" @visible="translationOpen=$event" />
    <MessageTranscript v-if="['audio','voice'].includes(data.kind) && !message._pending" :message="message" />
    <dl
      v-if="data.form_response"
      class="rounded border p-3 text-sm space-y-2"
      aria-label="Submitted form"
    >
      <div v-for="(value, key) in data.form_response" :key="key">
        <dt class="font-medium break-words">{{ key.replaceAll("_", " ") }}</dt>
        <dd class="whitespace-pre-wrap break-words text-ink-gray-6">
          {{
            typeof value === "object" ? JSON.stringify(value) : String(value)
          }}
        </dd>
      </div>
    </dl>
    <div
      v-if="reactionLabels(message.reactions).length"
      class="flex flex-wrap gap-1"
      aria-label="Reactions"
    >
      <span
        v-for="reaction in reactionLabels(message.reactions)"
        :key="reaction"
        class="rounded-full bg-surface-gray-2 px-2 py-1"
        >{{ reaction }}</span
      >
    </div>
    <span v-if="message.edited_at" class="text-xs text-ink-gray-5">Edited</span>
  </div>
</template>
