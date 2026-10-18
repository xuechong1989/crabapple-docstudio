<template>
  <div class="itp-preview-area" :class="{ 'itp-has-preview': previewUrl }">
    <!-- 文件路径栏 -->
    <div class="itp-path-bar" v-if="selectedPath">
      <span class="itp-path-text" :title="selectedPath">{{ selectedPath }}</span>
    </div>

    <template v-if="previewUrl">
      <!-- 左侧原图 -->
      <div
        class="itp-preview-panel"
        @wheel.prevent="$emit('wheel', $event)"
        @mousedown="$emit('drag-start', $event)"
        @mousemove="$emit('drag-move', $event)"
        @mouseup="$emit('drag-end', $event)"
        @mouseleave="$emit('drag-end', $event)"
      >
        <div class="itp-preview-title">
          <span class="itp-title-tag itp-tag-gray">原图区</span>
        </div>
        <div class="itp-preview-content" ref="leftContainerRef">
          <div class="image-container">
            <img
              :src="previewUrl"
              :style="imageStyle"
              class="preview-image"
              draggable="false"
              @load="$emit('image-load')"
            />
          </div>
        </div>
      </div>

      <!-- 右侧修图区 -->
      <div
        class="itp-preview-panel itp-preview-panel-right"
        @wheel.prevent="$emit('wheel', $event)"
      >
        <div class="itp-preview-title">
          <span class="itp-title-tag itp-tag-gray">修图区</span>
        </div>
        <div class="itp-preview-content itp-editable edited-panel" ref="rightContainerRef">
          <div class="image-container">
            <img
              v-if="!isLoadingCleaned"
              :src="cleanedPreviewUrl"
              :style="imageStyle"
              class="preview-image"
              draggable="false"
              ref="cleanedImageRef"
              @load="$emit('cleaned-image-load')"
            />
            <div v-else class="itp-loading-placeholder">
              <div class="itp-spinner"></div>
              <span>加载中...</span>
            </div>
            <canvas
              v-if="!isLoadingCleaned"
              ref="editCanvasRef"
              class="edit-canvas"
              :style="canvasStyle"
              @mousedown.prevent.stop="$emit('draw-start', $event)"
              @mousemove="$emit('draw-move', $event)"
              @mouseup="$emit('draw-end', $event)"
              @mouseleave="$emit('draw-end', $event)"
            ></canvas>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="itp-scan-placeholder" style="margin: auto;">
      <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 空状态emoji换单色线性SVG -->
      <div class="placeholder-icon"><AppIcon name="image" :size="44" /></div>
      <p>选择文件进行预览</p>
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：空态副提示文字按用户要求删除 -->
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
// xuechong 2026-10-09 研发BUG-0071 图标组件：空状态 emoji 换单色线性 SVG
import AppIcon from './AppIcon.vue'

defineProps({
  selectedPath: String,
  previewUrl: String,
  cleanedPreviewUrl: String,
  isLoadingCleaned: Boolean,
  imageStyle: Object,
  canvasStyle: Object
})

defineEmits(['image-load', 'cleaned-image-load', 'wheel', 'drag-start', 'drag-move', 'drag-end', 'draw-start', 'draw-move', 'draw-end'])

const leftContainerRef = ref(null)
const rightContainerRef = ref(null)
const cleanedImageRef = ref(null)
const editCanvasRef = ref(null)

defineExpose({
  leftContainerRef,
  rightContainerRef,
  cleanedImageRef,
  editCanvasRef
})
</script>

<style scoped>
.preview-hint {
  margin-top: 8px;
  font-size: 14px;
  color: #bbb;
}
</style>
