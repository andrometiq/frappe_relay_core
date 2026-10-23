<script setup>
import { inject, ref, watch } from "vue";
import { Button, FormControl } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const { group, groupInfo, busy, manageGroup, run, execute, enqueue, notice } = inject(whatsappKey);
const photo = ref(null), photoInput = ref(null), messageId = ref(""), action = ref("pin"), days = ref(7), deleting = ref(false), confirmation = ref("");
watch(group, () => {photo.value=null;messageId.value="";deleting.value=false;confirmation.value="";if(photoInput.value)photoInput.value.value="";});
async function uploadPhoto() {
  await run(async () => {
    const file = photo.value;
    if (!file || file.type !== "image/jpeg" || !file.size || file.size > 5*1024*1024) throw Error("Choose a JPEG up to 5 MiB.");
    const encoded = await new Promise((resolve,reject) => { const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error("Could not read this photo."));reader.readAsDataURL(file); });
    await execute("groups.photo", {id:group.value,photo_base64:encoded});
    photo.value=null;if(photoInput.value)photoInput.value.value="";notice.value="Group photo updated.";
  });
}
async function remove() {
  if (!busy.value && confirmation.value === group.value) await manageGroup("groups.delete");
}
async function pin() {
  await run(async () => {
    await enqueue("groups.pin", {id:group.value,reply_to:messageId.value.trim(),action:action.value,expiration_days:action.value==='pin'?Number(days.value):0}, [""]);
    messageId.value="";
  });
}
</script>
<template>
  <details class="border rounded p-4 space-y-3">
    <summary class="cursor-pointer text-sm font-medium">More group actions</summary>
    <Button label="Create invite link" :disabled="busy" @click="manageGroup('groups.invite.create')" />
    <form class="space-y-2" @submit.prevent="uploadPhoto">
      <label class="block text-sm">Group photo<input ref="photoInput" class="block w-full text-sm mt-2" type="file" accept="image/jpeg" :disabled="busy" @change="photo=$event.target.files?.[0]||null" /></label>
      <p class="text-xs text-ink-gray-5">Square JPEG, 192–2048 pixels per side, up to 5 MiB.</p>
      <Button type="submit" label="Update group photo" :disabled="busy || !photo" />
    </form>
    <form class="space-y-2" @submit.prevent="pin">
      <FormControl label="Group message ID" v-model="messageId" :disabled="busy" required />
      <RelaySelect label="Pin action" v-model="action" :options="[{label:'Pin message',value:'pin'},{label:'Unpin message',value:'unpin'}]" :disabled="busy" />
      <FormControl v-if="action==='pin'" label="Pin duration (days)" type="number" v-model="days" :min="1" :max="30" :disabled="busy" required />
      <Button type="submit" label="Queue pin change" :disabled="busy || !messageId.trim() || (action==='pin' && (!Number.isInteger(Number(days)) || days<1 || days>30))" />
    </form>
    <Button label="Delete group…" :disabled="busy" @click="deleting=!deleting;confirmation=''" />
    <form v-if="deleting" class="space-y-2" @submit.prevent="remove">
      <p class="text-sm">Delete {{ groupInfo.subject || group }}? This removes the group. Type its group ID to confirm: {{ group }}</p>
      <FormControl label="Confirm group ID" v-model="confirmation" :disabled="busy" />
      <Button type="submit" label="Delete this group" :disabled="busy || confirmation!==group" />
    </form>
  </details>
</template>
