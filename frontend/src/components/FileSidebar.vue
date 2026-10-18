<template>
  <aside class="itp-file-manager">
    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：模式+上传下拉经本插槽进入栏内顶部
         （与文件树连成一张卡、灰色分割线分开） -->
    <slot name="top-actions"></slot>

    <!-- xuechong 2026-06-01 上传中简易提示（详细进度见弹窗） -->
    <div v-if="isUploading" class="itp-uploading-hint">
      <span class="itp-spinner-sm"></span>
      <span>正在上传中...</span>
      <button class="itp-btn-cancel-upload" @click="$emit('cancel-upload')" title="取消上传">✕</button>
    </div>

    <div v-if="currentTask" class="itp-task-info">
      <div class="folder-name">{{ currentTask.folder_name }}</div>
      <div class="folder-desc">共 {{ currentTask.total_files }} 个文件</div>
    </div>

    <template v-if="fileTree.children?.length">
      <div class="itp-file-tree-header">
        <span>图片列表</span>
        <div class="itp-tree-actions">
          <!-- xuechong 2026-10-09 研发BUG-0071 树操作按钮：emoji 换单色线性 SVG 图标 -->
          <button @click="$emit('delete')" :disabled="!selectedPath || selectedPath === '.' || isBusy" title="删除选中"><AppIcon name="trash" :size="14" /></button>
          <button @click="$emit('expand-all')" title="展开全部"><AppIcon name="chevrons-down" :size="14" /></button>
          <button @click="$emit('collapse-all')" title="收起全部"><AppIcon name="chevrons-up" :size="14" /></button>
        </div>
      </div>
      <div class="itp-file-tree">
        <TreeNode
          v-for="child in fileTree.children"
          :key="child.path"
          :node="child"
          :selected-path="selectedPath"
          :expanded-paths="expandedPaths"
          @select="$emit('select', $event)"
          @toggle="$emit('toggle', $event)"
        />
      </div>
    </template>

    <div v-else class="itp-empty-state">
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：空态提示文字按用户要求删除，仅保留图标 -->
      <div class="empty-icon"><AppIcon name="folder" :size="44" /></div>
    </div>

    <!-- 删除确认对话框 -->
    <Transition name="ds-modal">
    <div v-if="showDeleteConfirm" class="itp-delete-overlay">
      <div class="itp-delete-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />确认删除</h4>
        <p>是否删除所选图片或文件夹？</p>
        <div class="itp-delete-actions">
          <button class="itp-btn itp-btn-default" @click="$emit('cancel-delete')"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-danger" @click="$emit('confirm-delete')"><AppIcon name="trash" :size="13" /> 确定</button>
        </div>
      </div>
    </div>
    </Transition>
  </aside>
</template>

<script setup>
import TreeNode from './TreeNode.vue'
// xuechong 2026-10-09 研发BUG-0071 图标组件：树操作/空状态图标（上传入口迁出后仍保留）
import AppIcon from './AppIcon.vue'

// xuechong 2026-10-09 研发BUG-0071 上传入口迁至页面级后，本组件不再发出 folder-upload/image-upload
// （2026-06-01 cancel-upload 取消上传保留）
const emit = defineEmits(['expand-all', 'collapse-all', 'select', 'toggle', 'delete', 'confirm-delete', 'cancel-delete', 'cancel-upload'])

defineProps({
  currentTask: Object,
  fileTree: Object,
  selectedPath: String,
  expandedPaths: Object,
  uploadProgress: Object,
  isBusy: Boolean,
  showDeleteConfirm: Boolean,
  isUploading: Boolean  // xuechong 2026-06-01 是否正在上传
})
</script>
