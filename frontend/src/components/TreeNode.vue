<template>
  <div class="tree-node-wrapper">
    <div
      class="tree-node"
      :class="{ selected: selectedPath === node.path, folder: node.type === 'directory' }"
      @click="handleClick"
    >
      <span v-if="node.type === 'directory'" class="toggle-icon" @click.stop="$emit('toggle', node.path)" :title="isExpanded ? '收起文件夹' : '展开文件夹'">
        {{ isExpanded ? '▼' : '▶' }}
      </span>
      <span v-else class="toggle-icon empty"></span>

      <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
           文件类型图标：emoji 换单色线性 SVG（目录folder/图片image/文档file/PDF file-text） -->
      <span class="node-icon">
        <AppIcon v-if="node.type === 'directory'" name="folder" :size="14" />
        <AppIcon v-else :name="getFileIcon(node.extension)" :size="14" />
      </span>
      <span class="node-name" :title="node.name">{{ node.name }}</span>
      <span v-if="node.size" class="node-size">{{ formatSize(node.size) }}</span>
    </div>

    <div v-if="node.type === 'directory' && isExpanded" class="tree-children">
      <TreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :selected-path="selectedPath"
        :expanded-paths="expandedPaths"
        @select="$emit('select', $event)"
        @toggle="$emit('toggle', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
// xuechong 2026-10-09 研发BUG-0071 文件类型图标换 SVG 图标组件
import AppIcon from './AppIcon.vue'

const props = defineProps({
  node: { type: Object, required: true },
  selectedPath: { type: String, default: '' },
  expandedPaths: { type: [Set], default: () => new Set() }
})

const emit = defineEmits(['select', 'toggle'])

const isExpanded = computed(() => props.expandedPaths.has(props.node.path))

function handleClick() {
  emit('select', props.node)
  // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
  // 文件夹整行点击即展开/收起（此前只有行首小图标能切换，用户反馈不便）：
  // 选中照旧（处理目标=点击的文件夹），展开状态跟着切换；行首小图标保留且带
  // .stop 防止二次触发。文件行行为不变（仅选中预览）
  if (props.node.type === 'directory') {
    emit('toggle', props.node.path)
  }
}

// xuechong 2026-10-09 研发BUG-0071 返回值从 emoji 改为 AppIcon 图标名（纯展示映射，无业务逻辑变化）
function getFileIcon(ext) {
  const icons = {
    '.png': 'image',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.bmp': 'image',
    '.tif': 'file',
    '.tiff': 'file',
    '.webp': 'image',
    '.pdf': 'file-text'
  }
  return icons[ext?.toLowerCase()] || 'file'
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
</script>

<style scoped>
.tree-node-wrapper {
  user-select: none;
}

.tree-node {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  gap: 6px;
}

/* xuechong 2026-10-09 研发BUG-0071 悬停/选中行配色并入设计令牌（原旧橙渐变） */
.tree-node:hover {
  background: var(--primary-light-bg, #FFF7ED);
}

.tree-node.selected {
  background: #EA580C;
  color: white;
}

.tree-node.selected .node-size {
  color: rgba(255, 255, 255, 0.8);
}

.toggle-icon {
  width: 16px;
  font-size: 14px;
  color: #6B7280;
  flex-shrink: 0;
}

.toggle-icon.empty {
  visibility: hidden;
}

.node-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.node-name {
  flex: 1;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-size {
  font-size: 14px;
  color: #9CA3AF;
  flex-shrink: 0;
}

.tree-children {
  padding-left: 20px;
}
</style>
