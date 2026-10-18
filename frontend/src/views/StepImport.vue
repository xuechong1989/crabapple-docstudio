<template>
  <div class="itp-right-panel">
    <ActionBar
      :preview-url="previewUrl"
      :current-file-path="currentFilePath"
      :sibling-images="siblingImages"
      :current-image-index="currentImageIndex"
      :can-go-prev="canGoPrev"
      :can-go-next="canGoNext"
      :can-batch-clean="canBatchClean"
      :is-batch-cleaning="isBatchCleaning"
      :is-rotating="isRotating"
      :can-undo="canUndo"
      :can-redo="canRedo"
      :has-edits="hasEdits"
      :can-restore="canRestore"
      :can-single-clean="canSingleClean"
      :actions-locked="actionsLocked"
      :add-page-number="addPageNumber"
      :show-page-toggle="showPageToggle"
      @update:add-page-number="$emit('update:add-page-number', $event)"
      @prev-image="$emit('prev-image')"
      @next-image="$emit('next-image')"
      @rotate="$emit('rotate', $event)"
      @single-clean="$emit('single-clean')"
      @batch-clean="$emit('batch-clean')"
      @stop-batch-clean="$emit('stop-batch-clean')"
      @undo="$emit('undo')"
      @redo="$emit('redo')"
      @save="$emit('save')"
      @restore="$emit('restore')"
      @redraw-enhance="$emit('redraw-enhance')"
      @redraw-weaken="$emit('redraw-weaken')"
      @redraw-enhance-batch="$emit('redraw-enhance-batch')"
      @redraw-weaken-batch="$emit('redraw-weaken-batch')"
      @redraw-settings="$emit('redraw-settings')"
    />

    <PreviewPanel
      ref="previewPanel"
      :selected-path="selectedPath"
      :preview-url="previewUrl"
      :cleaned-preview-url="cleanedPreviewUrl"
      :is-loading-cleaned="isLoadingCleaned"
      :image-style="imageStyle"
      :canvas-style="canvasStyle"
      @image-load="$emit('image-load')"
      @cleaned-image-load="$emit('cleaned-image-load')"
      @wheel="$emit('wheel', $event)"
      @drag-start="$emit('drag-start', $event)"
      @drag-move="$emit('drag-move', $event)"
      @drag-end="$emit('drag-end', $event)"
      @draw-start="$emit('draw-start', $event)"
      @draw-move="$emit('draw-move', $event)"
      @draw-end="$emit('draw-end', $event)"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ActionBar from '../components/ActionBar.vue'
import PreviewPanel from '../components/PreviewPanel.vue'

defineProps({
  selectedPath: String,
  previewUrl: String,
  cleanedPreviewUrl: String,
  isLoadingCleaned: Boolean,
  currentFilePath: String,
  siblingImages: Array,
  currentImageIndex: Number,
  canGoPrev: Boolean,
  canGoNext: Boolean,
  canBatchClean: Boolean,
  isBatchCleaning: Boolean,
  canSingleClean: Boolean,
  isRotating: Boolean,
  canUndo: Boolean,
  canRedo: Boolean,
  hasEdits: Boolean,
  canRestore: Boolean,
  // xuechong 2026-10-11 研发BUG-0073 处理锁定：透传给 ActionBar（页面传 isBusy，处理期间按钮禁用）
  actionsLocked: {
    type: Boolean,
    default: false
  },
  // xuechong 2026-10-11 研发BUG-0074 生成页码开关（v-model 透传）与显隐（嵌入模式 false）
  addPageNumber: {
    type: Boolean,
    default: true
  },
  showPageToggle: {
    type: Boolean,
    default: true
  },
  imageStyle: Object,
  canvasStyle: Object
})

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 补齐一键修图/批量修图/停止修图/批量重绘的事件透传：原缺失导致步骤1点击菜单项事件凭空消失（零反馈根因）
defineEmits(['prev-image', 'next-image', 'rotate', 'single-clean', 'batch-clean', 'stop-batch-clean', 'undo', 'redo', 'save', 'restore', 'image-load', 'cleaned-image-load', 'wheel', 'drag-start', 'drag-move', 'drag-end', 'draw-start', 'draw-move', 'draw-end', 'redraw-enhance', 'redraw-weaken', 'redraw-enhance-batch', 'redraw-weaken-batch', 'redraw-settings', 'update:add-page-number'])

const previewPanel = ref(null)

defineExpose({ previewPanel })
</script>
