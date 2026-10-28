<script setup>
import { Button, Dropdown } from "@relay/ui";
defineProps({ actions: Array, menuIcon: { type: String, default: "more-horizontal" } });
</script>
<template>
  <div class="conversation-tools">
    <div class="conversation-tool-buttons">
      <slot />
      <Dropdown :options="actions"><Button :icon="menuIcon" aria-label="Conversation actions" title="Conversation actions" /></Dropdown>
    </div>
  </div>
</template>
