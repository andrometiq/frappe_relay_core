<script setup>
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import BusinessRecordPicker from "../BusinessRecordPicker.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const {
  recordingBlob, recordingCallId, recordingSaved,
  callPermission,
  recording,
  recordingURL,
  busy,
  notice,
  contact,
  text,
  callId,
  callState,
  supported,
  remoteAudio,
  acceptCall,
  rejectCall,
  execute,
  run,
  startCall,
  endCall,
  stopRecording,
  startRecording,
} = inject(whatsappKey);
async function archiveRecording(){await run(async()=>{
 if(!recordingBlob.value||!recordingCallId.value)throw Error('No completed recording is available');
 const data=new FormData();data.append('provider_id',recordingCallId.value);data.append('file',recordingBlob.value,'relay-call.webm');
 const response=await fetch('/api/method/relay_core.call_records.upload_recording',{method:'POST',credentials:'same-origin',headers:{'X-Frappe-CSRF-Token':window.frappe?.csrf_token||window.csrf_token||''},body:data});
 const result=await response.json().catch(()=>null);
 if(!response.ok||!result?.message?.name)throw Error('Recording could not be archived. The local download remains available; retry after checking access and upload limits.');
 recordingSaved.value=result.message.name;notice.value='Recording archived in call history';
})}
</script>
<template>
  <div class="space-y-4">
    <Badge :label="callState" />
    <div class="flex flex-wrap gap-3">
      <Button
        label="Request call permission"
        :disabled="busy || !supported || !contact"
        @click="
          run(async () => {
            await execute('calls.permission.request');
            notice = 'Permission request sent';
          })
        "
      /><Button
        label="Call"
        :disabled="
          busy ||
          !supported ||
          !contact ||
          !!callId ||
          callState === 'Outcome unknown'
        "
        @click="startCall"
      /><Button
        v-if="callState === 'Incoming call'"
        label="Answer"
        :disabled="busy"
        @click="acceptCall"
      /><Button
        v-if="callState === 'Incoming call'"
        label="Decline"
        :disabled="busy"
        @click="rejectCall"
      /><Button
        label="End call"
        :disabled="busy || !supported || !callId"
        @click="endCall"
      />
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <Button
        label="Check permission"
        :disabled="busy || !supported || !contact"
        @click="
          run(async () => {
            const r = await execute('calls.permission.get');
            callPermission = r.permission?.status || 'Unknown';
          })
        "
      /><Badge v-if="callPermission" :label="callPermission" /><Button
        v-if="!recording"
        label="Record call"
        :disabled="busy || callState !== 'Connected'"
        @click="startRecording"
      /><Button v-else label="Stop recording" @click="stopRecording" /><a
        v-if="recordingURL"
        :href="recordingURL"
        download="relay-call.webm"
        class="text-sm text-blue-600"
        >Download recording</a
      >
    <Button v-if="recordingBlob&&!recordingSaved" label="Archive recording" :disabled="busy" @click="archiveRecording"/><span v-if="recordingSaved" class="text-sm">Recording archived</span>
    </div>
  </div>
</template>
