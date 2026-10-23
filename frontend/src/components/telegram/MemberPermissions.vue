<script setup>
import { inject, ref, watch } from "vue";
import { Button, FormControl } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import PermissionFields from "./PermissionFields.vue";
import { memberRights, adminRights, permissionValues } from "../../services/telegramPermissions";
import { telegramKey } from "../../composables/telegramContext";
import { positiveInteger } from "../formValidation";
const {member,userId,info,busy,run,operation,lookup,notice} = inject(telegramKey);
const permissions=ref({}), rights=ref({}), duration=ref('0'), customTitle=ref('');
watch(member, value=>{permissions.value=permissionValues(memberRights,value?.status==='restricted'?value:info.value?.permissions);rights.value=permissionValues(adminRights,value);customTitle.value=value?.custom_title||'';duration.value='0';},{immediate:true});
async function save(kind) {
  await run(async () => {
    const id=positiveInteger(userId.value,'user ID');
    if(member.value?.user?.id!==id)throw Error('Find this member before changing permissions.');
    const args={user_id:id};
    if(kind==='restrict') {args.permissions={...permissions.value};args.until_date=duration.value==='0'?0:Math.floor(Date.now()/1000)+Number(duration.value);}
    if(kind==='promote')args.administrator_rights={...rights.value};
    if(kind==='title')args.custom_title=customTitle.value;
    await operation('members.'+kind,args);await lookup();notice.value='Member settings updated';
  });
}
</script>
<template>
  <div class="space-y-3">
    <details class="border rounded p-3 space-y-3">
      <summary class="cursor-pointer text-sm font-medium">Member permissions</summary>
      <p class="text-xs text-ink-gray-5">Set the member’s allowed actions. Unchecked actions are disabled.</p>
      <PermissionFields v-model="permissions" :rights="memberRights" :disabled="busy" />
      <RelaySelect v-model="duration" label="Permission duration" :options="[{label:'Until changed',value:'0'},{label:'1 hour',value:'3600'},{label:'1 day',value:'86400'},{label:'7 days',value:'604800'}]" :disabled="busy" />
      <Button label="Save member permissions" :disabled="busy" @click="save('restrict')" />
    </details>
    <details class="border rounded p-3 space-y-3">
      <summary class="cursor-pointer text-sm font-medium">Administrator rights</summary>
      <p class="text-xs text-ink-gray-5">Choose the exact administrator rights to grant. Clearing every right removes administrator privileges where Telegram permits it.</p>
      <PermissionFields v-model="rights" :rights="adminRights" :disabled="busy" />
      <Button label="Save administrator rights" :disabled="busy" @click="save('promote')" />
      <FormControl v-model="customTitle" label="Administrator title" :maxlength="16" :disabled="busy" />
      <Button label="Save administrator title" :disabled="busy" @click="save('title')" />
    </details>
  </div>
</template>
