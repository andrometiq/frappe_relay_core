<script setup>
import MemberPermissions from "./MemberPermissions.vue";
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import MessageContent from "../MessageContent.vue";
import { objectValue } from "../messageContent";
import { telegramKey } from "../../composables/telegramContext";
const {
  cursor,
  busy,
  members,
  count,
  text,
  userId,
  member,
  run,
  operation,
  lookup,
  memberAction,
} = inject(telegramKey);
</script>
<template>
  <div class="space-y-3">
    <Button
      label="Load administrators"
      :disabled="busy"
      @click="
        run(async () => {
          members = await operation('administrators');
          count = await operation('count');
        })
      "
    /><Badge v-if="count !== null" :label="count + ' members'" />
    <div
      v-for="entry in members"
      :key="entry.user.id"
      class="flex justify-between gap-3 rounded border p-3"
    >
      <span>{{ entry.user.first_name }}</span
      ><span>{{ entry.status }}</span
      ><Button
        label="Select member"
        @click="
          userId = String(entry.user.id);
          member = entry;
        "
      />
    </div>
    <div class="flex items-end gap-2">
      <FormControl label="User ID" v-model="userId" :disabled="busy" /><Button
        label="Find member"
        :disabled="busy || !userId"
        @click="run(lookup)"
      />
    </div>
    <div class="flex flex-wrap gap-2">
      <Button
        label="Approve join request"
        :disabled="busy || !userId"
        @click="run(() => memberAction('requests.approve'))"
      /><Button
        label="Reject join request"
        :disabled="busy || !userId"
        @click="run(() => memberAction('requests.reject'))"
      />
    </div>
    <div v-if="member" class="rounded border p-3 space-y-3">
      <p>{{ member.user.first_name }} · {{ member.status }}</p>
      <details>
        <summary class="text-sm cursor-pointer">Membership actions</summary>
        <div class="flex gap-2 pt-3">
          <Button
            label="Ban member"
            :disabled="busy"
            @click="run(() => memberAction('members.ban'))"
          /><Button
            label="Unban member"
            :disabled="busy"
            @click="run(() => memberAction('members.unban'))"
          />
        </div>
      </details>
      <MemberPermissions />
    </div>
  </div>
</template>
