<template>
  <!-- 一键修图进度 -->
  <div v-if="showBatchCleanProgress" class="itp-progress-bar-container">
    <div class="itp-progress-header">
      <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
           进度/横幅 emoji 图标换单色线性 SVG（✕ 文本符号保留） -->
      <span class="itp-progress-title"><AppIcon name="tool" :size="14" /> {{ batchCleanStatus.message }}</span>
      <div class="itp-progress-stats">
        <span v-if="batchCleanStatus.current_path"><AppIcon name="folder" :size="14" /> {{ batchCleanStatus.current_path }}</span>
        <span><AppIcon name="clock" :size="14" /> {{ formatTime(batchCleanElapsed) }}</span>
        <span>{{ batchCleanStatus.progress }}%</span>
        <button
          v-if="batchCleanStatus.status === 'completed' || batchCleanStatus.status === 'failed' || batchCleanStatus.status === 'cancelled'"
          class="itp-progress-close"
          @click="$emit('close-batch-clean')"
        >✕</button>
      </div>
    </div>
    <div class="itp-progress-bar">
      <div
        class="itp-progress-fill animated batch-clean"
        :class="{ completed: batchCleanStatus.status === 'completed', failed: batchCleanStatus.status === 'failed' }"
        :style="{ width: batchCleanStatus.progress + '%' }"
      ></div>
    </div>
  </div>

  <!-- 处理进度 -->
  <div v-else-if="isProcessing" class="itp-progress-bar-container">
    <div class="itp-progress-header">
      <span class="itp-progress-title">{{ statusMessage }}</span>
      <div class="itp-progress-stats">
        <span><AppIcon name="clock" :size="14" /> {{ formatTime(processElapsed) }}</span>
        <span>{{ progress }}%</span>
      </div>
    </div>
    <div class="itp-progress-bar">
      <div class="itp-progress-fill animated" :style="{ width: progress + '%' }"></div>
    </div>
  </div>

  <!-- 完成横幅 -->
  <div v-else-if="showDownloadBtn" class="itp-complete-banner">
    <span class="complete-icon"><AppIcon name="check-circle" :size="18" /></span>
    <span class="complete-text">{{ statusMessage }}</span>
    <button class="itp-btn itp-btn-orange" @click="$emit('preview-pdf')" title="预览PDF"><AppIcon name="eye" :size="14" /> 预览PDF</button>
    <button class="itp-btn itp-btn-orange" @click="$emit('download-pdf')" title="下载PDF"><AppIcon name="download" :size="14" /> 下载PDF</button>
    <button class="itp-banner-close" @click="$emit('close-banner')">✕</button>
  </div>
</template>

<script setup>
// xuechong 2026-10-09 研发BUG-0071 进度横幅图标：emoji 换单色线性 SVG 图标组件
import AppIcon from './AppIcon.vue'

defineProps({
  showBatchCleanProgress: Boolean,
  batchCleanStatus: Object,
  batchCleanElapsed: Number,
  isProcessing: Boolean,
  processElapsed: Number,
  showDownloadBtn: Boolean,
  statusMessage: String,
  progress: Number,
  formatTime: Function
})

defineEmits(['close-batch-clean', 'preview-pdf', 'download-pdf', 'close-banner'])
</script>
