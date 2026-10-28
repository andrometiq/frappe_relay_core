<script setup>
import { provide } from "vue";
import { Button, ErrorMessage, Badge } from "@relay/ui";
import ChoiceField from "./fields/ChoiceField.vue";
import { useTelegramGroups } from "../composables/useTelegramGroups";
import { telegramKey } from "../composables/telegramContext";
import GroupConversation from "./telegram/GroupConversation.vue";
import GroupDetails from "./telegram/GroupDetails.vue";
import GroupMembers from "./telegram/GroupMembers.vue";
import GroupInvites from "./telegram/GroupInvites.vue";
import GroupTopics from "./telegram/GroupTopics.vue";
const state = useTelegramGroups();
provide(telegramKey, state);
const {
  rows,
  cursor,
  configured,
  selected,
  tab,
  busy,
  error,
  notice,
  info,
  group,
  tabs,
  choose,
  run,
  directory,
  searchGroups,
} = state;
</script>
<template>
  <section
    class="page-body overflow-auto space-y-4"
    aria-label="Telegram groups"
  >
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-sm text-green-700">
      {{ notice }}
    </p>
    <div class="flex flex-wrap items-end gap-3">
      <ChoiceField
        class="min-w-0 flex-1"
        :field="{label:'Telegram group',search:searchGroups,readOnly:busy,hasMore:!!cursor,loadMore:(query,signal)=>searchGroups(query,signal,cursor)}"
        :model-value="selected"
        @update:modelValue="choose"
      /><Button
        label="Refresh groups"
        :loading="busy"
        @click="run(() => directory())"
      />
    </div>
    <div v-if="!rows.length && !busy" class="rounded border p-6 space-y-2">
      <h2 class="font-medium">
        {{ configured ? "No verified groups" : "Telegram is not configured" }}
      </h2>
      <p class="text-sm text-ink-gray-5">
        {{
          configured
            ? "Link an incoming group to a business contact and verify its endpoint."
            : "Configure Telegram in Hub and enable its Relay channel."
        }}
      </p>
      <a href="#/settings" class="text-sm text-blue-600">Open settings</a>
    </div>
    <template v-if="group">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-medium">{{ info?.title || group.label }}</h2>
        <Badge label="Telegram" theme="blue" />
      </div>
      <div class="flex flex-wrap gap-1" role="tablist" aria-label="Group tools">
        <Button
          v-for="name in tabs"
          :key="name"
          :label="name"
          role="tab"
          :aria-selected="tab === name"
          :variant="tab === name ? 'subtle' : 'ghost'"
          @click="tab = name"
        />
      </div>
      <div class="workflow-card max-w-3xl">
        <GroupConversation v-if="tab === 'Conversation'" />
        <GroupDetails v-if="tab === 'Details'" />
        <GroupMembers v-if="tab === 'Members'" />
        <GroupInvites v-if="tab === 'Invites'" />
        <GroupTopics v-if="tab === 'Topics'" />
      </div>
    </template>
  </section>
</template>
