<template>
  <div class="file-tree">
    <TreeNode 
      v-for="child in tree.children" 
      :key="child.path"
      :node="child"
      :selected-path="selectedPath"
      :expanded-paths="expandedPaths"
      @select="$emit('select', $event)"
      @toggle="$emit('toggle', $event)"
    />
  </div>
</template>

<script setup>
import TreeNode from './TreeNode.vue'

defineProps({
  tree: { type: Object, required: true },
  selectedPath: { type: String, default: '' },
  expandedPaths: { type: Set, default: () => new Set() }
})

defineEmits(['select', 'toggle'])
</script>
