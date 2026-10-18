<template>
  <div class="image-preview" ref="containerRef">
    <img
      :src="src"
      :style="imageStyle"
      @wheel.prevent="handleWheel"
      @mousedown="startDrag"
      draggable="false"
    />
    <div class="preview-controls">
      <button @click="resetZoom"><AppIcon name="maximize" :size="13" /> 还原大小</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
// xuechong 2026-10-10 研发BUG-0071 用户复验：还原大小按钮补图标
import AppIcon from './AppIcon.vue'

const props = defineProps({
  src: { type: String, required: true }
})

const containerRef = ref(null)
const scale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })

const imageStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
  cursor: isDragging.value ? 'grabbing' : 'grab'
}))

function handleWheel(e) {
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  scale.value = Math.max(0.1, Math.min(5, scale.value * delta))
}

function startDrag(e) {
  if (isDragging.value) return
  isDragging.value = true
  dragStart.value = { x: e.clientX - offsetX.value, y: e.clientY - offsetY.value }
  document.addEventListener('mousemove', drag)
  document.addEventListener('mouseup', stopDrag)
}

function drag(e) {
  if (!isDragging.value) return
  offsetX.value = e.clientX - dragStart.value.x
  offsetY.value = e.clientY - dragStart.value.y
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('mousemove', drag)
  document.removeEventListener('mouseup', stopDrag)
}

onUnmounted(function () {
  document.removeEventListener('mousemove', drag)
  document.removeEventListener('mouseup', stopDrag)
})

function resetZoom() {
  scale.value = 1
  offsetX.value = 0
  offsetY.value = 0
}

watch(() => props.src, () => {
  scale.value = 1
  offsetX.value = 0
  offsetY.value = 0
})
</script>

<style scoped>
.image-preview {
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-preview img {
  max-width: 100%;
  max-height: 100%;
  transition: transform 0.1s;
  user-select: none;
}

.preview-controls {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 8px;
}

.preview-controls button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: rgba(255,255,255,0.9);
  border: 1px solid #ccc;
  border-radius: 4px;
  cursor: pointer;
}
</style>
