<script setup>
import AutomationSettings from "./AutomationSettings.vue";
import AutomationPolicies from "./AutomationPolicies.vue";
import { onMounted, ref } from "vue";
import { coreApi } from "../services/coreApi";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
const config = ref({}),
  token = ref(""),
  callbackSecret = ref(""),
  error = ref(""),
  notice = ref(""),
  busy = ref(false),
  canConfigure = ref(false);
async function load() {
  try {
    config.value = await coreApi("settings.connection");
    canConfigure.value = config.value.can_configure;
  } catch (e) {
    error.value = e.message;
  }
}
async function save() {
  if (busy.value || !canConfigure.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await coreApi(
      "settings.save_connection",
      {
        url: config.value.url,
        account: config.value.account,
        token: token.value,
        callback_secret: callbackSecret.value,
      },
      true,
    );
    token.value = "";
    callbackSecret.value = "";
    notice.value = "Connection saved";
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(load);
const links = [
  ["Relay channels", "relay-channel"],
  ["Contact types", "relay-contact-type"],
  ["Contacts", "relay-contact"],
  ["Verified endpoints", "relay-contact-endpoint"],
  ["Tickets", "relay-ticket"],
  ["Canned replies", "relay-canned-reply"],
  ["Email automatic replies", "relay-email-rule"],
  ["AI providers", "relay-ai-provider"],
  ["Automation policies", "relay-automation-policy"],
  ["Message actions", "relay-message-action"],
  ["Incoming events", "relay-hub-event"],
];
</script>
<template>
  <section class="page-body space-y-6 overflow-auto">
    <form class="max-w-2xl space-y-4" @submit.prevent="save">
      <h2 class="text-lg font-medium">Hub connection</h2>
      <ErrorMessage :message="error" />
      <p v-if="notice" role="status">{{ notice }}</p>
      <FormControl
        label="Hub MCP URL"
        v-model="config.url"
        :disabled="!canConfigure"
        placeholder="https://hub.example.com/mcp"
      /><FormControl
        label="Hub account"
        v-model="config.account"
        :disabled="!canConfigure"
      /><FormControl
        v-if="canConfigure"
        label="Hub API token"
        type="password"
        autocomplete="new-password"
        v-model="token"
        :placeholder="
          config.token_configured ? 'Saved — leave blank to keep' : ''
        "
      /><FormControl
        v-if="canConfigure"
        label="Callback signing secret"
        type="password"
        autocomplete="new-password"
        v-model="callbackSecret"
        :placeholder="
          config.callback_configured ? 'Saved — leave blank to keep' : ''
        "
      /><Button
        v-if="canConfigure"
        type="submit"
        label="Save connection"
        variant="solid"
        :loading="busy"
      />
    </form>
    <AutomationSettings v-if="canConfigure" />
    <AutomationPolicies v-if="canConfigure" />
    <div class="grid sm:grid-cols-2 gap-3 max-w-3xl">
      <a
        v-for="[label, route] in links"
        :key="route"
        :href="'/desk/' + route"
        class="rounded border p-4 text-sm hover:bg-surface-gray-2"
        >{{ label }}</a
      >
    </div>
  </section>
</template>
