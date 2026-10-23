<script setup>
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import MessageContent from "../MessageContent.vue";
import { objectValue } from "../messageContent";
import { telegramKey } from "../../composables/telegramContext";
const { busy, notice, invite, inviteName, approval, run, operation } =
  inject(telegramKey);
</script>
<template>
  <div class="space-y-3">
    <FormControl label="Invite name" v-model="inviteName" /><FormControl
      type="checkbox"
      label="Require approval"
      v-model="approval"
    /><Button
      label="Create invite"
      :disabled="busy"
      @click="
        run(async () => {
          invite = (
            await operation('invite.create', {
              name: inviteName,
              creates_join_request: approval,
            })
          ).invite_link;
          notice = 'Invite created';
        })
      "
    /><FormControl label="Invite link" v-model="invite" />
    <div class="flex gap-2">
      <Button
        label="Update invite"
        :disabled="busy || !invite"
        @click="
          run(async () => {
            await operation('invite.edit', {
              invite_link: invite,
              name: inviteName,
              creates_join_request: approval,
            });
            notice = 'Invite updated';
          })
        "
      /><Button
        label="Revoke invite"
        :disabled="busy || !invite"
        @click="
          run(async () => {
            await operation('invite.revoke', { invite_link: invite });
            invite = '';
            notice = 'Invite revoked';
          })
        "
      />
    </div>
  </div>
</template>
