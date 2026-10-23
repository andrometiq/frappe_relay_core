<script setup>
import { computed, provide, watch } from "vue";
import { ErrorMessage } from "@relay/ui";
import { useWhatsAppTemplatesWorkspace } from "../composables/whatsapp/useWhatsAppTemplatesWorkspace";
import { useWhatsAppIdentity } from "../composables/useWhatsAppIdentity";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { whatsappKey } from "../composables/whatsapp/context";
import WhatsAppTemplates from "./whatsapp/WhatsAppTemplates.vue";
import LoadingRows from "./LoadingRows.vue";
import WorkspaceState from "./WorkspaceState.vue";
import FrappePageHeader from "./frappe/FrappePageHeader.vue";
const props = defineProps({
  initialTab: { type: String, default: "Templates" },
  focused: Boolean,
});
const workspace = useWhatsAppTemplatesWorkspace();
const { identity, error: metadataError, load: refreshMetadata } = useWhatsAppIdentity({ immediate: false });
watch(() => workspace.supported.value, value => { if (value) refreshMetadata(); });
useRealtimeRefresh([], ["templates"], () => { if (workspace.supported.value) return refreshMetadata(); });
provide(whatsappKey, workspace);
const {
  busy,
  error,
  notice,
  capabilities,
  supported,
} = workspace;
const unavailable = computed(() => !busy.value && (!capabilities.value || (error.value && !workspace.templates.value.length && !workspace.creating.value)));
</script>
<template>
  <div class="whatsapp-template-workspace">
    <div v-if="!unavailable && (error || notice)" class="v1-template-feedback">
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
    </div>
    <template v-if="unavailable">
      <FrappePageHeader title="Message templates" />
      <WorkspaceState :title="error ? 'Templates are temporarily unavailable' : 'Connect WhatsApp to get started'" :description="error ? 'Relay couldn’t load templates from Hub. Review the connection in setup, then return to Templates.' : 'Finish the WhatsApp channel setup for this site to load and manage approved messages.'" icon="message-circle">
        <a class="relay-button relay-button--solid" href="#/settings">Open setup</a>
      </WorkspaceState>
    </template>
    <template v-else-if="capabilities && !supported">
      <FrappePageHeader title="Message templates" />
      <WorkspaceState title="Template management is disabled" description="Enable message templates in this account’s WhatsApp channel settings in Relay Hub." icon="file-text"><a class="relay-button relay-button--solid" href="#/settings">Open setup</a></WorkspaceState>
    </template>
    <template v-else-if="capabilities && supported"><p class="px-4 py-2 text-xs text-ink-gray-5">Metadata sync: {{ identity?.status || 'Not checked' }} · Last successful sync: {{ identity?.updated || 'Not available' }}</p><ErrorMessage :message="metadataError" /><WhatsAppTemplates /></template>
    <template v-else>
      <FrappePageHeader title="Message templates" />
      <LoadingRows label="Loading templates…" :count="6" />
    </template>
  </div>
</template>
