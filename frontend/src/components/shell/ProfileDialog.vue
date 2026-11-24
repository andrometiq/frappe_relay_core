<script setup>
import { computed, ref, watch } from 'vue'
import { Avatar, Button, Dialog, ErrorMessage, FormControl, toast } from '@relay/ui'
import { CLEAR_AFTER, STATUSES, applyPreferences, changedFields, loadMyProfile, myProfile, saveMyProfile, setDensity } from '../../services/userProfiles'
import { setTheme, theme } from '../../services/theme'
import { uploadFile } from '../../services/uploadFile'

// Raven-style profile: photo, name, status and personal preferences. Theme and density preview until Cancel.
const open = defineModel({ type: Boolean, default: false })
const form = ref(null), clearAfter = ref(null), busy = ref(false), uploading = ref(false), error = ref('')
const photoInput = ref(null)
let shown = null
const MAX_PHOTO_BYTES = 5 * 1024 * 1024
const NOTIFICATIONS = [['notify_messages', 'New message in my chats'], ['notify_mentions', 'Mentions and assignments'], ['notify_sound', 'Sound']]
const name = computed(() => form.value?.display_name || form.value?.full_name || '')
// While a clear time is set, the first choice keeps it.
const clearOptions = computed(() => myProfile.value?.status_clear_at ? [{ value: 'keep', label: 'Keep current time' }, ...CLEAR_AFTER] : CLEAR_AFTER)
const clearHint = computed(() => clearAfter.value === null && myProfile.value?.status_clear_at
  ? 'Clears ' + new Date(myProfile.value.status_clear_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '')

// Opening only reads the profile; the theme and density on screen are kept so Cancel can restore them.
watch(open, async value => {
  if (!value) return
  shown = { theme: theme.value, density: document.documentElement.dataset.density }
  error.value = ''
  clearAfter.value = null
  form.value = myProfile.value ? { ...myProfile.value } : null
  try { form.value = { ...await loadMyProfile() } } catch (e) { error.value = e.message }
}, { immediate: true })

function preview(field, value) {
  form.value[field] = value
  if (field === 'theme') setTheme(value.toLowerCase())
  else setDensity(value)
}
function restore() {
  if (shown) { setTheme(shown.theme); setDensity(shown.density) }
  shown = null
}
// Unsaved edits: changed fields or a new clear time.
const dirty = computed(() => !!form.value && !!myProfile.value && (Object.keys(changedFields(form.value, myProfile.value)).length > 0 || clearAfter.value !== null))
function cancel() {
  restore()
  open.value = false
}
// A click outside or Escape keeps unsaved edits unless the person chooses to discard them.
function dismiss() {
  if (dirty.value && !window.confirm('Discard your profile changes?')) return
  cancel()
}
async function choosePhoto(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!file.type.startsWith('image/') || file.size > MAX_PHOTO_BYTES) {
    error.value = 'Choose an image of 5 MB or less.'
    return
  }
  error.value = ''
  uploading.value = true
  try {
    form.value.user_image = await uploadFile(file, 'The photo could not be uploaded. Try again.',
      { isPrivate: false, doctype: 'User', docname: form.value.user, fieldname: 'user_image' })
  }
  catch (e) { error.value = e.message }
  finally { uploading.value = false }
}
async function save() {
  const values = changedFields(form.value, myProfile.value)
  if (clearAfter.value !== null) values.clear_after = clearAfter.value
  busy.value = true
  error.value = ''
  try {
    if (Object.keys(values).length) await saveMyProfile(values)
    // Save keeps what the person sees, even when it equals the saved profile; only Cancel restores the page.
    shown = null
    applyPreferences(form.value)
    open.value = false
    toast('Profile saved')
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>

<template>
  <Dialog :model-value="open" :options="{ title: 'Your profile' }" class="profile-dialog" @update:model-value="value => value || dismiss()">
    <form v-if="form" id="relay-profile-form" class="profile-form" @submit.prevent="save">
      <ErrorMessage :message="error" />
      <section class="profile-photo">
        <Avatar :label="name" :image="form.user_image || undefined" :status="form.status" size="xl" />
        <div class="profile-photo-copy">
          <strong>{{ name }}</strong><span>{{ form.user }}</span>
          <div class="profile-photo-actions">
            <Button :label="form.user_image ? 'Change photo' : 'Upload photo'" variant="outline" icon-left="camera" :loading="uploading" @click="photoInput.click()" />
            <Button v-if="form.user_image" label="Remove" theme="red" variant="outline" :disabled="uploading" @click="form.user_image = ''" />
            <input ref="photoInput" type="file" accept="image/*" hidden @change="choosePhoto" />
          </div>
        </div>
      </section>
      <div class="profile-grid">
        <FormControl v-model="form.display_name" label="Display name" :placeholder="form.full_name" maxlength="80" />
        <FormControl v-model="form.job_title" label="Job title" placeholder="Sales coordinator" maxlength="80" />
      </div>
      <fieldset class="profile-group">
        <legend>Status</legend>
        <div class="profile-statuses" role="radiogroup" aria-label="Status">
          <button v-for="status in STATUSES" :key="status" type="button" role="radio" class="profile-status" :aria-checked="form.status === status" @click="form.status = status">
            <span class="profile-status-dot" :data-status="status" aria-hidden="true" />{{ status }}
          </button>
        </div>
        <div class="profile-grid profile-grid--status">
          <FormControl v-model="form.status_text" label="Custom status" placeholder="At dispatch till 4 PM" maxlength="100" />
          <FormControl :model-value="clearAfter ?? clearOptions[0].value" type="select" label="Clear after" :options="clearOptions" @update:model-value="clearAfter = $event === 'keep' ? null : $event" />
        </div>
        <p v-if="clearHint" class="profile-hint">{{ clearHint }}</p>
      </fieldset>
      <div class="profile-grid">
        <div class="profile-group">
          <span class="profile-label" id="relay-profile-theme">Theme</span>
          <div class="relay-segmented" role="radiogroup" aria-labelledby="relay-profile-theme">
            <button v-for="theme in ['Light', 'Dark', 'System']" :key="theme" type="button" role="radio" :aria-checked="form.theme === theme" @click="preview('theme', theme)">{{ theme }}</button>
          </div>
        </div>
        <div class="profile-group">
          <span class="profile-label" id="relay-profile-density">Message density</span>
          <div class="relay-segmented" role="radiogroup" aria-labelledby="relay-profile-density">
            <button v-for="density in ['Comfortable', 'Compact']" :key="density" type="button" role="radio" :aria-checked="form.density === density" @click="preview('density', density)">{{ density }}</button>
          </div>
        </div>
      </div>
      <fieldset class="profile-group">
        <legend>Notifications</legend>
        <button v-for="[field, label] in NOTIFICATIONS" :key="field" type="button" role="switch" class="profile-switch-row" :aria-checked="Boolean(form[field])" @click="form[field] = form[field] ? 0 : 1">
          <span>{{ label }}</span><span class="relay-switch" :aria-checked="Boolean(form[field])" aria-hidden="true" />
        </button>
      </fieldset>
    </form>
    <p v-else-if="!error" class="profile-hint" role="status">Loading your profile…</p>
    <ErrorMessage v-else :message="error" />
    <template #actions>
      <Button label="Cancel" variant="ghost" @click="cancel" />
      <Button label="Save" variant="solid" type="submit" form="relay-profile-form" :loading="busy" :disabled="!form || uploading" />
    </template>
  </Dialog>
</template>

<style scoped>
.profile-form { display: flex; flex-direction: column; gap: 18px; }
.profile-photo { display: flex; align-items: center; gap: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--relay-stroke); }
.profile-photo :deep(.relay-avatar) { width: 72px; height: 72px; border-radius: 18px; font-size: 26px; }
.profile-photo-copy { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.profile-photo-copy strong { font-size: 15px; }
.profile-photo-copy span { overflow: hidden; color: var(--relay-ink-3); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.profile-photo-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.profile-grid--status { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); margin-top: 10px; }
.profile-group { display: flex; flex-direction: column; gap: 6px; min-width: 0; border: 0; padding: 0; margin: 0; }
.profile-group legend, .profile-label { margin-bottom: 6px; color: var(--relay-ink-3); font-size: 12px; font-weight: 500; }
.profile-statuses { display: flex; flex-wrap: wrap; gap: 6px; }
.profile-status { display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 0 11px; border: 1px solid var(--relay-stroke-strong); border-radius: 999px; color: var(--relay-ink-2); font-size: 12.5px; transition: background-color var(--relay-fast) ease, border-color var(--relay-fast) ease; }
.profile-status:hover { background: var(--relay-hover); }
.profile-status[aria-checked=true] { border-color: var(--relay-accent); background: var(--relay-accent-soft); color: var(--relay-accent-text); font-weight: 500; }
.profile-status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--relay-status-available); }
.profile-status-dot[data-status=Busy] { background: var(--relay-status-busy); }
.profile-status-dot[data-status=Away] { background: var(--relay-status-away); }
.profile-status-dot[data-status='Do not disturb'] { background: var(--relay-status-dnd); }
.profile-hint { color: var(--relay-ink-3); font-size: 12px; }
.profile-switch-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 36px; padding: 0 4px; border-radius: 6px; color: var(--relay-ink); font-size: 13.5px; text-align: left; transition: background-color var(--relay-fast) ease; }
.profile-switch-row:hover { background: var(--relay-hover); }
.profile-switch-row:focus-visible { outline: 2px solid var(--relay-accent); outline-offset: 2px; }
@media (max-width: 768px) {
  .profile-grid, .profile-grid--status { grid-template-columns: 1fr; }
  .profile-switch-row { min-height: 44px; }
}
</style>
