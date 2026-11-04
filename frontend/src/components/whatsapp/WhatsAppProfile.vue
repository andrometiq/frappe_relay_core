<script setup>
import { onMounted, ref } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { photoProblem, profileChanges, profileDraft, VERTICALS } from '../../services/channelSetup'

const props = defineProps({ channel: { type: String, required: true }, label: { type: String, default: '' } })
const emit = defineEmits(['close'])
const original = ref(null), draft = ref(profileDraft()), photo = ref(null), busy = ref(false), error = ref('')

async function load() {
  try {
    original.value = await coreApi('channels_api.number_profile', { channel: props.channel })
    draft.value = profileDraft(original.value)
  } catch (e) { error.value = e.message }
}
function choose(event) {
  const file = event.target.files?.[0] || null
  error.value = photoProblem(file); photo.value = error.value ? null : file
}
function readPhoto(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
    reader.onerror = () => reject(Error('The photo could not be read.'))
    reader.readAsDataURL(file)
  })
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const values = { channel: props.channel, profile: profileChanges(original.value, draft.value) }
    if (photo.value) Object.assign(values, { photo_base64: await readPhoto(photo.value), photo_type: photo.value.type })
    original.value = await coreApi('channels_api.save_number_profile', values, true)
    toast('Profile saved'); emit('close')
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <Dialog :model-value="true" :options="{ title: 'WhatsApp profile' + (label ? ' · ' + label : ''), size: 'lg' }" :disable-outside-click-to-close="busy" @update:model-value="value => { if (!value) emit('close') }">
    <form class="whatsapp-profile" @submit.prevent="save">
      <p class="text-sm text-ink-gray-6">Customers see this profile in WhatsApp. To change the display name, use Meta WhatsApp Manager.</p>
      <ErrorMessage :message="error" />
      <p v-if="!original && !error" role="status">Reading profile…</p>
      <template v-if="original">
        <img v-if="original.profile_picture_url" :src="original.profile_picture_url" alt="Current profile photo" class="whatsapp-profile__photo" />
        <label class="whatsapp-profile__file">Profile photo (JPEG or PNG, up to 5 MB)<input type="file" accept="image/jpeg,image/png" :disabled="busy" @change="choose" /></label>
        <FormControl v-model="draft.about" label="About" maxlength="139" :disabled="busy" />
        <FormControl v-model="draft.description" label="Description" type="textarea" rows="3" maxlength="512" :disabled="busy" />
        <FormControl v-model="draft.address" label="Address" maxlength="256" :disabled="busy" />
        <FormControl v-model="draft.email" label="Email" type="email" maxlength="128" :disabled="busy" />
        <FormControl v-model="draft.websites" label="Websites (one per line, up to 2)" type="textarea" rows="2" :disabled="busy" />
        <FormControl v-model="draft.vertical" label="Business category" type="select" :options="VERTICALS" :disabled="busy" />
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" :disabled="busy" @click="emit('close')" />
          <Button type="submit" variant="solid" label="Save profile" :loading="busy" />
        </div>
      </template>
    </form>
  </Dialog>
</template>
<style scoped>
.whatsapp-profile { display:flex; flex-direction:column; gap:14px; min-width:0; }
.whatsapp-profile__photo { width:72px; height:72px; border-radius:50%; object-fit:cover; }
.whatsapp-profile__file { display:flex; flex-direction:column; gap:8px; font-size:14px; color:var(--ink-gray-8); }
.whatsapp-profile__file input { max-width:100%; min-height:44px; }
</style>
