<script setup>
import WorkspaceHeading from './WorkspaceHeading.vue'
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <WorkspaceHeading description="Access is shared across channels and assigned by business record type." />
    <article class="workflow-card"><h3>Relay Communication User</h3><p>Sees assigned business types in the inbox, contacts and tickets. Unlinked chats and contacts are shared so new senders can be triaged.</p></article>
    <article class="workflow-card"><h3>Relay Communication Manager</h3><p>Sees every enabled business type, prepares bulk campaigns and assigns users to business types in Settings.</p></article>
    <article class="workflow-card"><h3>System Manager</h3><p>Everything, including setup and channel configuration.</p></article>
    <p>Business type assignments apply inside Relay. Frappe Desk permissions are unchanged.</p>
  </div></section>
</template>
