<script setup>
import { computed, inject, ref, watch } from "vue";
import { Button, FormControl } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
import { templateParameterDescriptors, buildTemplateComponents, templatePreview } from "../../services/templateParameters";
const { group, busy, supported, capabilities, run, execute, enqueue } = inject(whatsappKey);
const file = ref(null), fileInput = ref(null);
const kind = ref("text"), text = ref(""), source = ref(""), sourceType = ref("url"), caption = ref(""), filename = ref(""), replyTo = ref(""), templates = ref([]), cursor = ref(""), templateId = ref(""), values = ref({});
const selected = computed(() => templates.value.find(t => t.id === templateId.value));
const fields = computed(() => templateParameterDescriptors(selected.value));
const preview = computed(() => templatePreview(selected.value, fields.value, values.value));
const kinds = computed(() => ['text','image','video','audio','document',...(capabilities.value?.templates ? ['template'] : [])].map(value => ({value,label:value[0].toUpperCase()+value.slice(1)})));
watch(templateId, () => {values.value={};});
watch(group, () => {file.value=null;if(fileInput.value)fileInput.value.value="";text.value="";source.value="";caption.value="";filename.value="";replyTo.value="";values.value={};});
async function loadTemplates(next=false) {
  await run(async () => {
    const result=await execute('templates.list', next ? {after:cursor.value} : {});
    templates.value=(result.data||[]).filter(t=>t.status==='APPROVED');
    cursor.value=result.paging?.cursors?.after||"";templateId.value="";
  });
}
async function send() {
  if (!group.value || !supported.value) return;
  await run(async () => {
    let operation, args={id:group.value};
    if(kind.value==='text') {
      if(!text.value.trim())throw Error('Enter a message.');
      operation='groups.send';args.body=text.value;
    } else if(kind.value==='template') {
      if(!selected.value || selected.value.status!=='APPROVED')throw Error('Select an approved template.');
      operation='groups.template';Object.assign(args,{name:selected.value.name,language:selected.value.language,components:buildTemplateComponents(fields.value,values.value)});
    } else {
      operation='groups.media';args.media_type=kind.value;
      if(sourceType.value==='file') {
        if(!file.value || !file.value.size || file.value.size>4*1024*1024)throw Error('Choose a file up to 4 MiB.');
        args.content_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not read this file.'));reader.readAsDataURL(file.value);});
        args.mime_type=file.value.type || 'application/octet-stream';
        if(kind.value==='document')args.filename=file.value.name;
      } else {
        if(!source.value.trim())throw Error('Enter a media URL or uploaded media ID.');
        args[sourceType.value==='url'?'media_url':'media_id']=source.value.trim();
      }
      if(['image','video','document'].includes(kind.value))args.caption=caption.value;
      if(kind.value==='document' && sourceType.value!=='file')args.filename=filename.value;
    }
    if(replyTo.value.trim())args.reply_to=replyTo.value.trim();
    await enqueue(operation,args,[""]);
    file.value=null;if(fileInput.value)fileInput.value.value="";
    text.value="";source.value="";caption.value="";filename.value="";replyTo.value="";values.value={};
  });
}
</script>
<template>
  <form class="space-y-3 border-t pt-4" @submit.prevent="send">
    <h3 class="font-medium text-sm">Message this group</h3>
    <RelaySelect v-model="kind" label="Group message type" :options="kinds" :disabled="busy" />
    <FormControl v-if="kind==='text'" label="Group message" type="textarea" v-model="text" :maxlength="4096" :disabled="busy" required />
    <template v-else-if="kind==='template'">
      <div class="flex gap-2"><Button label="Load approved group templates" :disabled="busy" @click="loadTemplates()" /><Button v-if="cursor" label="Next group templates" :disabled="busy" @click="loadTemplates(true)" /></div>
      <RelaySelect v-model="templateId" label="Group template" :options="templates.map(t=>({label:t.name+' · '+t.language,value:t.id}))" :disabled="busy" />
      <p v-if="!templates.length" class="text-sm text-ink-gray-5">Load templates to select an approved one. Later pages may contain more approved templates.</p>
      <p v-if="selected" class="text-sm whitespace-pre-wrap rounded bg-surface-gray-2 p-3">{{ preview }}</p>
      <FormControl v-for="field in fields" :key="field.key" v-model="values[field.key]" :label="field.label+(field.kind==='media'?' (public URL or media ID)':'')" :disabled="busy" required />
    </template>
    <template v-else>
      <RelaySelect v-model="sourceType" label="Media source" :options="[{label:'Local file',value:'file'},{label:'Public URL',value:'url'},{label:'Uploaded media ID',value:'id'}]" :disabled="busy" />
      <label v-if="sourceType==='file'" class="block text-sm">Group attachment<input ref="fileInput" type="file" class="block w-full text-sm mt-2" :disabled="busy" @change="file=$event.target.files?.[0]||null" /><span class="text-xs text-ink-gray-5">Up to 4 MiB. Choose a format supported by the selected media type.</span></label>
      <FormControl v-else v-model="source" :label="sourceType==='url'?'Group media URL':'Group media ID'" :disabled="busy" required />
      <FormControl v-if="['image','video','document'].includes(kind)" v-model="caption" label="Group media caption" type="textarea" :maxlength="1024" :disabled="busy" />
      <FormControl v-if="kind==='document' && sourceType!=='file'" v-model="filename" label="Group document filename" :disabled="busy" />
    </template>
    <FormControl v-model="replyTo" label="Reply to message ID (optional)" :disabled="busy" />
    <Button type="submit" label="Queue group message" variant="solid" :disabled="busy || !supported || !group || (kind==='text' && !text.trim()) || (kind==='template' && !selected) || (!['text','template'].includes(kind) && (sourceType==='file' ? !file : !source.trim()))" />
  </form>
</template>
