<script setup>
import { Button, FormControl } from "@relay/ui";
import { ref } from "vue";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
const filtersOpen=ref(false);
function timeLabel(value){if(!value)return '';const date=new Date(value.replace(' ','T'));return Number.isNaN(date.getTime())?'':date.toLocaleDateString()===new Date().toLocaleDateString()?date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):date.toLocaleDateString([],{day:'numeric',month:'short'})}
defineProps({
  contacts: Array,
  query: String,
  starred: Boolean,
  mode: {type:String,default:'all'},
  folder: String,
  team: String,
  selected: String,
  busy: Boolean,
  previous: Object,
  next: Object,
  businessMode: Boolean,
});
defineEmits([
  "update:starred",
  "update:mode",
  "update:folder",
  "update:team",
  "update:query",
  "search",
  "start",
  "select",
  "page",
]);
</script>
<template>
  <aside class="contact-directory" aria-label="Conversation contacts">
    <template v-if="businessMode"><slot name="scope"/><slot /></template>
    <template v-else>
      <div class="directory-heading">
        <h2>Conversations</h2>
        <button type="button" class="directory-filter-button" :aria-expanded="filtersOpen" @click="filtersOpen=!filtersOpen">Filters<span v-if="starred || folder || team" class="filter-indicator" /></button>
      </div>
      <div class="px-4 pb-2"><Button label="New conversation" icon-left="plus" :disabled="busy" @click="$emit('start')"/></div>
      <slot name="scope" />
      <form class="directory-search" @submit.prevent="$emit('search')">
        <FormControl
          :model-value="query"
          @update:model-value="$emit('update:query', $event)"
          type="search"
          placeholder="Search conversations"
          aria-label="Search business contacts"
        /><Button icon="search" label="Search" title="Search" :disabled="busy" type="submit" />
      </form>
      <div class="directory-tabs" aria-label="Conversation filters"><button v-for="item in [['all','All'],['unread','Unread'],['unassigned','Unassigned']]" :key="item[0]" :aria-pressed="mode===item[0]" :class="{active:mode===item[0]}" :disabled="busy" @click="$emit('update:mode',item[0]);$emit('search')">{{item[1]}}</button></div>
      <form v-if="filtersOpen" class="directory-filters px-4 pb-3 space-y-2" @submit.prevent="$emit('search')">
        <FormControl
          type="checkbox"
          label="Starred conversations"
          :model-value="starred"
          @update:model-value="
            $emit('update:starred', $event);
            $emit('search');
          "
        />
        <RemoteLinkField :field="{label:'Team',method:'teams.filter_options'}" :model-value="team" @update:model-value="$emit('update:team',$event);$emit('search')"/>
        <div class="flex gap-2 items-end">
          <FormControl
            label="Folder"
            placeholder="All folders"
            :model-value="folder"
            @update:model-value="$emit('update:folder', $event)"
          /><Button label="Apply folder" type="submit" :disabled="busy" />
        </div>
      </form>
      <div class="directory-rows">
        <button
          v-for="contact in contacts"
          :key="contact.name"
          class="directory-contact"
          :class="{ selected: selected === contact.name }"
          :disabled="busy"
          :aria-pressed="selected === contact.name"
          :data-contact="contact.name"
          @click="$emit('select', contact.name)"
        >
          <span class="contact-avatar">{{
            (contact.display_name || contact.name).slice(0, 1).toUpperCase()
          }}</span
          ><span class="directory-contact-copy"><span class="directory-contact-top"><strong>{{ contact.display_name || contact.name }}</strong><time>{{timeLabel(contact.latest_at)}}</time></span><span class="directory-contact-bottom"><small>{{contact.latest_preview || 'No messages yet'}}</small><span v-if="contact.unread" class="directory-unread">{{contact.unread}}{{contact.unread_more?'+':''}}</span></span></span>
        </button>
        <p v-if="!contacts.length && !busy" class="p-4 text-sm text-ink-gray-5">
          No conversations found. Try another search or change your filters.
        </p>
      </div>
      <div v-if="previous || next" class="directory-pagination">
        <Button
          label="Previous contacts"
          :disabled="busy || !previous"
          @click="$emit('page', previous)"
        /><Button
          label="Next contacts"
          :disabled="busy || !next"
          @click="$emit('page', next)"
        />
      </div>
    </template>
  </aside>
</template>
