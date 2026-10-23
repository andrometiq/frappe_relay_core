<script setup>
import GroupAdministration from "./GroupAdministration.vue";
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import MessageContent from "../MessageContent.vue";
import { objectValue } from "../messageContent";
import { telegramKey } from "../../composables/telegramContext";
const { busy, title, description, group, run, saveDetails } =
  inject(telegramKey);
</script>
<template>
  <form class="space-y-3" @submit.prevent="run(saveDetails)">
    <FormControl label="Group title" v-model="title" /><FormControl
      type="textarea"
      label="Description"
      v-model="description"
    /><Button
      type="submit"
      label="Save group"
      variant="solid"
      :disabled="busy || !title.trim()"
    />
  </form>
  <GroupAdministration />
</template>
