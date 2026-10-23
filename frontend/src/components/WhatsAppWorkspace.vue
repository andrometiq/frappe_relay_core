<script setup>
import { provide, watch } from "vue";
import { Button, ErrorMessage, FeatherIcon } from "@relay/ui";
import { useWhatsAppTemplatesWorkspace } from "../composables/whatsapp/useWhatsAppTemplatesWorkspace";
import { useWhatsAppIdentity } from "../composables/useWhatsAppIdentity";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { whatsappKey } from "../composables/whatsapp/context";
import WhatsAppTemplates from "./whatsapp/WhatsAppTemplates.vue";
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
  refresh,
} = workspace;
</script>
<template>
  <div class="whatsapp-template-workspace">
    <div v-if="error || notice" class="v1-template-feedback">
      <ErrorMessage :message="error" />
      <p v-if="notice" role="status">{{ notice }}</p>
    </div>
    <template v-if="!capabilities && !busy">
      <FrappePageHeader title="Message templates" />
      <div class="template-workspace-empty">
        <span class="template-workspace-empty-mark" aria-hidden="true"><FeatherIcon name="message-circle" :size="22" /></span>
        <h2>Connect WhatsApp in Relay Hub</h2>
        <p>Finish the WhatsApp channel setup for this site in Relay Hub. Then check the connection to load its Meta templates.</p>
        <Button label="Check connection" variant="solid" :loading="busy" @click="refresh" />
      </div>
    </template>
    <template v-else-if="capabilities && !supported">
      <FrappePageHeader title="Message templates" />
      <div class="template-workspace-empty">
        <span class="template-workspace-empty-mark" aria-hidden="true"><FeatherIcon name="file-text" :size="22" /></span>
        <h2>Template management is disabled</h2>
        <p>Enable message templates in this account’s WhatsApp channel settings in Relay Hub.</p>
      </div>
    </template>
    <template v-else-if="capabilities && supported"><p class="px-4 py-2 text-xs text-ink-gray-5">Metadata sync: {{ identity?.status || 'Not checked' }} · Last successful sync: {{ identity?.updated || 'Not available' }}</p><ErrorMessage :message="metadataError" /><WhatsAppTemplates /></template>
    <template v-else>
      <FrappePageHeader title="Message templates" />
      <div class="template-workspace-loading" role="status">Loading templates…</div>
    </template>
  </div>
</template>
