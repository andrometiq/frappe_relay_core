<script setup>
import { inject, ref, watch } from "vue";
import { Button, FormControl } from "@relay/ui";
import PermissionFields from "./PermissionFields.vue";
import { memberRights, permissionValues } from "../../services/telegramPermissions";
import { telegramKey } from "../../composables/telegramContext";
import { positiveInteger } from "../formValidation";
const {info,group,busy,run,operation,notice,directory}=inject(telegramKey);
const permissions=ref({}),photo=ref(null),photoInput=ref(null),message=ref(''),sender=ref(''),leaving=ref(false),confirmation=ref('');
watch(info,value=>{permissions.value=permissionValues(memberRights,value?.permissions);},{immediate:true});
watch(group,()=>{photo.value=null;message.value='';sender.value='';leaving.value=false;confirmation.value='';});
async function change(op,args={}) {await run(async()=>{await operation(op,args);notice.value='Group action confirmed';});}
async function savePermissions(){await run(async()=>{await operation('permissions',{permissions:{...permissions.value}});info.value=await operation('info');notice.value='Default permissions updated';});}
async function upload(){await run(async()=>{const file=photo.value;if(!file||file.type!=='image/jpeg'||!file.size||file.size>5*1024*1024)throw Error('Choose a JPEG up to 5 MiB.');const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not read this photo.'));reader.readAsDataURL(file);});await operation('photo.set',{photo_base64:encoded});photo.value=null;if(photoInput.value)photoInput.value.value='';notice.value='Group photo updated';});}
async function pin(action){await run(async()=>{await operation('pins.'+action,{message_id:positiveInteger(message.value,'message ID')});notice.value='Pinned message updated';});}
async function senderAction(action){await run(async()=>{const id=Number(sender.value);if(!Number.isSafeInteger(id)||id>=0||Math.abs(id)>=2**52)throw Error('Enter a negative posting-channel ID.');await operation('members.'+action,{sender_chat_id:id});notice.value='Posting-channel restriction updated';});}
async function leave(){if(busy.value||confirmation.value!==String(group.value?.chat_id))return;await run(async()=>{await operation('leave');await directory();notice.value='The bot left the group';});}
</script>
<template>
  <div class="space-y-3 border-t pt-4">
    <details class="rounded border p-3 space-y-3"><summary class="text-sm font-medium cursor-pointer">Default member permissions</summary><p class="text-xs text-ink-gray-5">These are the allowed actions for ordinary members. Individual restrictions can override them.</p><PermissionFields v-model="permissions" :rights="memberRights" :disabled="busy" /><Button label="Save default permissions" :disabled="busy" @click="savePermissions" /></details>
    <details class="rounded border p-3 space-y-3"><summary class="text-sm font-medium cursor-pointer">Group photo</summary><label class="block text-sm">New group photo<input ref="photoInput" type="file" accept="image/jpeg" class="block w-full text-sm mt-2" :disabled="busy" @change="photo=$event.target.files?.[0]||null" /></label><p class="text-xs text-ink-gray-5">JPEG up to 5 MiB and 2048 × 2048 pixels.</p><div class="flex flex-wrap gap-2"><Button label="Upload Telegram group photo" :disabled="busy||!photo" @click="upload" /><Button label="Remove group photo" :disabled="busy" @click="change('photo.delete')" /></div></details>
    <details class="rounded border p-3 space-y-3"><summary class="text-sm font-medium cursor-pointer">Pinned messages</summary><FormControl v-model="message" label="Telegram message ID" :disabled="busy" /><div class="flex flex-wrap gap-2"><Button label="Pin message" :disabled="busy||!message" @click="pin('pin')" /><Button label="Unpin message" :disabled="busy||!message" @click="pin('unpin')" /><Button label="Unpin all group messages" :disabled="busy" @click="change('pins.unpin_all')" /></div></details>
    <details class="rounded border p-3 space-y-3"><summary class="text-sm font-medium cursor-pointer">Posting channels</summary><FormControl v-model="sender" label="Posting channel ID" :disabled="busy" /><div class="flex flex-wrap gap-2"><Button label="Ban posting channel" :disabled="busy||!sender" @click="senderAction('ban_sender')" /><Button label="Unban posting channel" :disabled="busy||!sender" @click="senderAction('unban_sender')" /></div></details>
    <Button label="Leave group…" :disabled="busy" @click="leaving=!leaving;confirmation=''" />
    <form v-if="leaving" class="rounded border p-3 space-y-3" @submit.prevent="leave"><p class="text-sm">The bot will stop receiving and sending group messages until it is added again. Type group ID {{ group.chat_id }} to confirm.</p><FormControl v-model="confirmation" label="Confirm Telegram group ID" :disabled="busy" /><Button type="submit" label="Make bot leave group" :disabled="busy||confirmation!==String(group.chat_id)" /></form>
  </div>
</template>
