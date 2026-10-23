<script setup>
import GroupComposer from "./GroupComposer.vue";
import GroupActions from "./GroupActions.vue";
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import BusinessRecordPicker from "../BusinessRecordPicker.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const {
  joinCursor, joinApprovalMode, nextJoinRequests, newGroupSubject, newGroupDescription,
  groupInfo,
  groupDescription,
  inviteLink,
  joinRequests,
  groupCursor,
  busy,
  groups,
  group,
  text,
  subject,
  template,
  supported,
  inspectGroup,
  manageGroup,
  nextGroups,
  createGroup,
  sendGroup,
} = inject(whatsappKey);
</script>
<template>
  <section class="workflow-card">
    <div class="flex items-end gap-3">
      <FormControl class="flex-1" label="New group" v-model="newGroupSubject" :maxlength="128" /><Button
        label="Create"
        :disabled="busy || !supported || !newGroupSubject.trim()"
        @click="createGroup"
      />
    </div>
    <FormControl label="New group description" v-model="newGroupDescription" type="textarea" :maxlength="2048" :disabled="busy" />
    <RelaySelect label="New group joining" v-model="joinApprovalMode" :disabled="busy" :options="[{label:'Require approval',value:'approval_required'},{label:'Automatically approve',value:'auto_approve'}]" />
    <RelaySelect
      label="Group"
      v-model="group"
      :disabled="busy"
      :options="groups.map((g) => ({ label: g.subject || g.id, value: g.id }))"
    /><Button
      v-if="groupCursor"
      label="Next groups"
      :disabled="busy"
      @click="nextGroups"
    /><Button
      label="Group settings"
      :disabled="busy || !supported || !group"
      @click="inspectGroup"
    />
    <div v-if="groupInfo" class="space-y-3 border rounded p-4">
      <FormControl label="Subject" v-model="subject" /><FormControl
        type="textarea"
        label="Description"
        v-model="groupDescription"
      />
      <div class="flex flex-wrap gap-2">
        <Button
          label="Save group"
          :disabled="busy"
          @click="
            manageGroup('groups.update', {
              subject,
              description: groupDescription,
            })
          "
        /><Button
          label="Show invite link"
          :disabled="busy"
          @click="manageGroup('groups.invite.get')"
        /><Button
          label="Reset invite link"
          :disabled="busy"
          @click="manageGroup('groups.invite.reset')"
        />
      </div>
      <p v-if="inviteLink" class="text-sm break-all">{{ inviteLink }}</p>
      <div
        v-for="p in groupInfo.participants || []"
        :key="p.wa_id || p.user"
        class="flex items-center gap-2 text-sm"
      >
        <span>{{ p.wa_id || p.user }}</span
        ><Button
          label="Remove"
          :disabled="busy"
          @click="
            manageGroup('groups.participants.remove', {
              participants: [p.wa_id || p.user],
            })
          "
        />
      </div>
      <h3 class="text-sm font-medium">Join requests</h3>
      <p v-if="!joinRequests.length" class="text-sm text-ink-gray-5">No requests on this page.</p>
      <div
        v-for="j in joinRequests"
        :key="j.join_request_id"
        class="flex flex-wrap items-center gap-2 text-sm"
      >
        <span>{{ j.wa_id }}</span
        ><Button
          label="Approve"
          :disabled="busy"
          @click="
            manageGroup('groups.requests.approve', {
              join_requests: [j.join_request_id],
            })
          "
        /><Button
          label="Reject"
          :disabled="busy"
          @click="
            manageGroup('groups.requests.reject', {
              join_requests: [j.join_request_id],
            })
          "
        />
      </div>
    </div>
    <Button v-if="joinCursor" label="Next join requests" :disabled="busy" @click="nextJoinRequests" />
    <GroupActions v-if="groupInfo && group" />
    <GroupComposer />
  </section>
</template>
