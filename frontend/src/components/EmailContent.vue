<script setup>
import { computed, ref } from "vue";
import { Button } from "@relay/ui";
const props = defineProps({ message: Object, email: Object });
const showHTML = ref(false);
const html = computed(
  () =>
    '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; img-src data:; style-src &apos;unsafe-inline&apos;"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    (props.email.html || ""),
);
function attachment(index) {
  return (
    "/api/method/relay_core.attachments.read?message=" +
    encodeURIComponent(props.message.name) +
    "&index=" +
    index +
    "&download=1"
  );
}
</script>
<template>
  <div class="space-y-2">
    <p v-if="email.to?.length" class="text-xs break-words">To: {{ email.to.join(', ') }}</p>
    <p v-if="email.cc?.length" class="text-xs break-words">CC: {{ email.cc.join(', ') }}</p>
    <strong v-if="email.subject">{{ email.subject }}</strong>
    <div v-if="email.html">
      <Button
        :label="showHTML ? 'Hide HTML email' : 'View HTML email'"
        @click="showHTML = !showHTML"
      /><iframe
        v-if="showHTML"
        sandbox
        :srcdoc="html"
        title="Email HTML preview"
        class="w-full h-80 rounded border mt-2"
        referrerpolicy="no-referrer"
      />
    </div>
    <div v-for="(file, index) in email.attachments || []" :key="index">
      <a
        :href="attachment(index)"
        target="_blank"
        rel="noopener noreferrer"
        class="underline"
        >Download {{ file.filename || "attachment" }}</a
      >
    </div>
  </div>
</template>
