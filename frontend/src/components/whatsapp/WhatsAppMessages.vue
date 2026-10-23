<script setup>
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import BusinessRecordPicker from "../BusinessRecordPicker.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const {
  incomingScroll,
  hasOlder,
  incoming,
  conversationBusy,
  mediaType,
  mediaURL,
  mediaCaption,
  mediaFilename,
  replyTo,
  messageText,
  busy,
  contact,
  text,
  template,
  supported,
  olderMessages,
  sendMessage,
} = inject(whatsappKey);
</script>
<template>
  <section class="workflow-card">
    <div
      v-if="incoming.length"
      ref="incomingScroll"
      class="space-y-2 max-h-72 overflow-auto border rounded p-3"
    >
      <Button
        v-if="hasOlder"
        label="Earlier messages"
        :loading="conversationBusy"
        @click="olderMessages"
      />
      <article
        v-for="m in incoming"
        :key="m.id"
        class="flex gap-3 items-start border-b py-2"
      >
        <p class="text-sm whitespace-pre-wrap break-words min-w-0 flex-1">
          {{ m.text }}
        </p>
        <Button label="Reply" @click="replyTo = m.id" />
      </article>
    </div>
    <RelaySelect
      label="Message type"
      v-model="mediaType"
      :options="['text', 'image', 'video', 'audio', 'document', 'sticker']"
    /><FormControl
      v-if="mediaType === 'text'"
      type="textarea"
      label="Message"
      v-model="messageText"
    /><template v-else
      ><FormControl
        label="Attachment URL (HTTPS)"
        v-model="mediaURL" /><FormControl
        v-if="['image', 'video', 'document'].includes(mediaType)"
        label="Caption"
        v-model="mediaCaption" /><FormControl
        v-if="mediaType === 'document'"
        label="Filename"
        v-model="mediaFilename"
    /></template>
    <div v-if="replyTo" class="flex items-center gap-2 text-sm text-ink-gray-5">
      <span>Replying to selected message</span
      ><Button label="Clear reply" @click="replyTo = ''" />
    </div>
    <Button
      label="Send message"
      :disabled="
        busy ||
        !supported ||
        !contact ||
        (mediaType === 'text' ? !messageText.trim() : !mediaURL.trim())
      "
      @click="sendMessage"
    />
  </section>
</template>
