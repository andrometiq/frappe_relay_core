<script setup>
import { ref, watch, onMounted, onBeforeUnmount, inject } from "vue";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import { stableSubmission } from "../../services/submission";
import { useTask } from "../../composables/useTask";
import { objectValue } from "../messageContent";
import SendChannel from "./SendChannel.vue";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { messagesKey } from '../../composables/messagesContext';
const {emailDrafts,beginEmail,finishEmail}=inject(messagesKey);
const props = defineProps({ source: Object });

const { busy, error, notice, run } = useTask(),
  to = ref([]),
  cc = ref([]),
  bcc = ref([]),
  subject = ref(""),
  body = ref(""),
  html = ref(""),
  forward = ref(false),
  files = ref([]),
  advanced = ref(false);
const draftKey=()=>props.source.channel+':'+props.source.sender_endpoint;
let previousKey;
const draftFields={to,cc,bcc,subject,body,html,forward,files,advanced};
function saveDraft() { if(!previousKey)return;const draft=Object.fromEntries(Object.entries(draftFields).map(([key,value])=>[key,value.value]));if(JSON.stringify(emailDrafts.get(previousKey))!==JSON.stringify(draft))emailDrafts.set(previousKey,draft);while(emailDrafts.size>30)emailDrafts.delete(emailDrafts.keys().next().value); }
watch(Object.values(draftFields),saveDraft,{deep:true});
onBeforeUnmount(saveDraft);
watch(()=>emailDrafts.get(draftKey()),saved=>{
  if(saved)for(const [key,value] of Object.entries(draftFields))value.value=saved[key];
});
watch(
  draftKey,
  () => {
    saveDraft();previousKey=draftKey();
    const saved=emailDrafts.get(previousKey);
    if(saved){for(const [key,value] of Object.entries(draftFields))value.value=saved[key];return;}
    to.value = props.source.sender_endpoint ? [props.source.sender_endpoint] : [];
    subject.value =
      "Re: " +
      (objectValue(props.source.provider_context).subject || "Conversation");
    body.value = "";
    html.value = "";
    cc.value = [];
    bcc.value = [];
    files.value = [];
    forward.value = false;
  },
  { immediate: true },
);
const signature = ref("");
onMounted(() =>
  run(async () => {
    signature.value = (await coreApi("email_preferences.read")).signature;
  }),
);
async function saveSignature() {
  await coreApi("email_preferences.save", { signature: signature.value }, true);
  notice.value = "Signature saved";
}
async function upload(selected) {
  if (files.value.length + selected.length > 8)
    throw Error("Choose at most eight attachments");
  for (const file of selected) {
    if (
      file.size < 1 ||
      file.size + files.value.reduce((sum, row) => sum + row.size, 0) >
        4 * 1024 * 1024
    )
      throw Error("Combined attachments must fit within 4 MiB");
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(Error("Could not read attachment"));
      reader.readAsDataURL(file);
    });
    files.value.push(
      await coreApi(
        "attachments.upload",
        {
          message: props.source.name,
          filename: file.name,
          content_base64: content,
        },
        true,
      ),
    );
  }
}
async function send() {
  const origin=props.source, originKey=draftKey();
  const values = {
    message: props.source.name,
    to: to.value,
    cc: cc.value,
    bcc: bcc.value,
    subject: subject.value,
    body: body.value,
    ...(html.value ? { html: html.value } : {}),
    attachment_ids: files.value.map((row) => row.name),
    forward: forward.value ? 1 : 0,
  };
  let pending;
  const result=await stableSubmission("email", values, async (key) => {
    pending=beginEmail(origin,values,key);
    try {
      const result=await coreApi("email.send", { ...values, request_key: key }, true);
      pending.action=result?.action;
      if(result?.status==='Rejected'){pending.status='Failed';throw Error('Email was rejected. Review the recipients and configuration.');}
      if(!result?.message)throw Error('Email delivery is not confirmed. Check status before retrying.');
      return result;
    } catch(error) {if(pending.status!=='Failed')pending.status='Unconfirmed';throw error;}
  });
  // Do not erase another conversation's draft when a slow request finishes.
  if(previousKey===originKey && body.value===values.body && html.value===(values.html||'') && emailDrafts.get(originKey)?.body===values.body) {
    body.value = "";html.value = "";files.value = [];
    saveDraft();notice.value = "Email sent";
  } else if(previousKey!==originKey) {
    const draft=emailDrafts.get(originKey);
    if(draft && draft.body===values.body)emailDrafts.set(originKey,{...draft,body:'',html:'',files:[]});
  }
  await finishEmail(pending,result);

}
function startForward() {
  forward.value = !forward.value;
  to.value = forward.value || !props.source.sender_endpoint ? [] : [props.source.sender_endpoint];
  cc.value = [];
  bcc.value = [];
  html.value = "";
  files.value = [];
  error.value = "";
  notice.value = "";
  subject.value =
    (forward.value ? "Fwd: " : "Re: ") +
    (objectValue(props.source.provider_context).subject || "Conversation");
  body.value = forward.value
    ? "\n\nForwarded message:\n" + props.source.content
    : "";
}
</script>
<template>
  <form class="message-composer email-composer" @submit.prevent="run(send)">
    <div class="composer-toolbar"><SendChannel :disabled="busy" /></div>
    <div class="flex flex-wrap items-center gap-2">
      <strong class="text-sm">{{
        forward ? "Forward email" : "Reply by email"
      }}</strong
      ><Button
        :label="forward ? 'Reply instead' : 'Forward instead'"
        :disabled="busy"
        @click="startForward"
      /><Button
        :label="advanced ? 'Hide email options' : 'Email options'"
        @click="advanced = !advanced"
      />
    </div>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status">{{ notice }}</p>
    <RemoteLinkField multiple v-model="to" :field="{label:'To', method:'email.recipient_options', maxLength:254, params:{message:source.name}, readOnly:busy, placeholder:'Search contact emails or enter an exact verified address'}" />
    <div v-if="advanced" class="grid sm:grid-cols-2 gap-3">
      <RemoteLinkField multiple v-model="cc" :field="{label:'CC', method:'email.recipient_options', maxLength:254, params:{message:source.name}, readOnly:busy}" />
      <RemoteLinkField multiple v-model="bcc" :field="{label:'BCC', method:'email.recipient_options', maxLength:254, params:{message:source.name}, readOnly:busy}" />
    </div>
    <FormControl label="Subject" v-model="subject" /><FormControl
      label="Email message"
      type="textarea"
      :rows="4"
      v-model="body"
    />
    <div v-if="advanced" class="space-y-2">
      <FormControl
        label="Saved signature"
        type="textarea"
        v-model="signature"
      />
      <div class="flex gap-2">
        <Button
          label="Save signature"
          :disabled="busy"
          @click="run(saveSignature)"
        /><Button
          label="Insert signature"
          :disabled="busy || !signature"
          @click="body += '\n\n' + signature"
        />
      </div>
    </div>
    <FormControl
      v-if="advanced"
      label="Optional HTML version"
      type="textarea"
      v-model="html"
    /><label class="text-sm"
      >Attachments (4 MiB combined)<input
        type="file"
        multiple
        aria-label="Email attachments"
        :disabled="busy"
        class="block max-w-full"
        @change="run(() => upload([...$event.target.files]))"
    /></label>
    <ul v-if="files.length" class="text-sm">
      <li
        v-for="file in files"
        :key="file.name"
        class="flex gap-2 items-center"
      >
        {{ file.filename
        }}<Button
          label="Remove attachment"
          :disabled="busy"
          @click="files = files.filter((row) => row.name !== file.name)"
        />
      </li>
    </ul>
    <Button
      label="Send email"
      type="submit"
      variant="solid"
      :disabled="busy || !to.length || !subject.trim() || !body.trim()"
    />
  </form>
</template>
