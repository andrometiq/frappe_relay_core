<script setup>
import { computed, provide } from "vue";
import { ErrorMessage } from "@relay/ui";
import { useWhatsAppTemplatesWorkspace } from "../composables/whatsapp/useWhatsAppTemplatesWorkspace";
import { whatsappKey } from "../composables/whatsapp/context";
import WhatsAppTemplates from "./whatsapp/WhatsAppTemplates.vue";
import LoadingRows from "./LoadingRows.vue";
import WorkspaceState from "./WorkspaceState.vue";
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
} = workspace;
const unavailable = computed(() => !busy.value && (!capabilities.value || (error.value && !workspace.templates.value.length && !workspace.creating.value)));
</script>
<template>
  <div class="whatsapp-template-workspace">
    <div v-if="!unavailable && (error || notice)" class="v1-template-feedback">
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
    </div>
    <template v-if="unavailable">
      <WorkspaceState :title="error ? 'Templates are temporarily unavailable' : 'Connect WhatsApp to get started'" :description="error ? 'Relay couldn’t load templates from Hub. Review the connection in setup, then return to Templates.' : 'Finish the WhatsApp channel setup for this site to load and manage approved messages.'" icon="message-circle">
        <a class="relay-button relay-button--solid" href="#/settings">Open setup</a>
      </WorkspaceState>
    </template>
    <template v-else-if="capabilities && !supported">
      <WorkspaceState title="Template management is disabled" description="Enable message templates in this account’s WhatsApp channel settings in Relay Hub." icon="file-text"><a class="relay-button relay-button--solid" href="#/settings">Open setup</a></WorkspaceState>
    </template>
    <WhatsAppTemplates v-else-if="capabilities && supported" />
    <template v-else>
      <LoadingRows label="Loading templates…" :count="6" />
    </template>
  </div>
</template>
