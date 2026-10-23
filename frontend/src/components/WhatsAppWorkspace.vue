<script setup>
import { provide } from "vue";
import { Button, ErrorMessage, FeatherIcon } from "@relay/ui";
import { useWhatsAppTemplatesWorkspace } from "../composables/whatsapp/useWhatsAppTemplatesWorkspace";
import { whatsappKey } from "../composables/whatsapp/context";
import WhatsAppTemplates from "./whatsapp/WhatsAppTemplates.vue";
import FrappePageHeader from "./frappe/FrappePageHeader.vue";
const props = defineProps({
  initialTab: { type: String, default: "Templates" },
  focused: Boolean,
});
const workspace = useWhatsAppTemplatesWorkspace();
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
    <div v-if="error || notice" class="template-workspace-feedback">
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
    <WhatsAppTemplates v-else-if="capabilities && supported" />
    <template v-else>
      <FrappePageHeader title="Message templates" />
      <div class="template-workspace-loading" role="status">Loading templates…</div>
    </template>
  </div>
</template>
