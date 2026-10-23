<script setup>
// Compatibility wrapper: rendering is delegated to Frappe DataTable's engine.
import FrappeRows from './FrappeRows.vue'
defineProps({items:{type:Array,required:true},rowHeight:{default:124},label:{default:'Records'}})
</script>
<template><FrappeRows :items="items" :row-height="rowHeight" :label="label"><template #default="{item}"><slot :item="item"/></template></FrappeRows></template>
