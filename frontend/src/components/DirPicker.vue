<template>
  <div class="dir-picker-modal">
    <div class="dir-picker-container">
      <div class="dir-picker-header">
        选择{{ type === 'source' ? '源' : '输出' }}目录
      </div>
      <div class="dir-picker-path">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 emoji换单色线性SVG（本组件当前无页面引用，同步保持一致） -->
        <button @click="goUp" :disabled="!parentPath"><AppIcon name="arrow-left" :size="14" /> 上级</button>
        <span style="margin-left: 10px;">{{ currentPath || '根目录' }}</span>
      </div>
      <div class="dir-picker-list">
        <div
          v-for="dir in directories"
          :key="dir.path"
          class="dir-picker-item"
          @click="navigateTo(dir)"
          @dblclick="selectDir(dir)"
        >
          <span><AppIcon :name="dir.type === 'drive' ? 'hard-drive' : 'folder'" :size="14" /></span>
          <span>{{ dir.name }}</span>
        </div>
        <div v-if="directories.length === 0" style="color: #999; text-align: center; padding: 20px;">
          空目录
        </div>
      </div>
      <div class="dir-picker-actions">
        <button class="btn" @click="$emit('close')"><AppIcon name="x" :size="13" /> 取消</button>
        <button class="btn btn-primary" @click="confirmSelect"><AppIcon name="check" :size="13" /> 确定选择当前目录</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { browseDirs } from '../api'
// xuechong 2026-10-09 研发BUG-0071 图标组件：目录选择器 emoji 换单色线性 SVG
import AppIcon from './AppIcon.vue'

const props = defineProps({
  type: { type: String, default: 'source' }
})

const emit = defineEmits(['select', 'close', 'error'])

const currentPath = ref('')
const parentPath = ref('')
const directories = ref([])

async function loadDirs(path = '') {
  try {
    const res = await browseDirs(path)
    currentPath.value = res.data.current_path
    parentPath.value = res.data.parent_path
    directories.value = res.data.directories
  } catch (e) {
    emit('error', '加载目录失败，请检查服务是否正常运行')
  }
}

function navigateTo(dir) {
  loadDirs(dir.path)
}

function goUp() {
  if (parentPath.value) {
    loadDirs(parentPath.value)
  } else {
    loadDirs('')
  }
}

function selectDir(dir) {
  if (dir.type === 'folder' || dir.type === 'directory') {
    emit('select', dir.path)
  } else {
    navigateTo(dir)
  }
}

function confirmSelect() {
  if (currentPath.value) {
    emit('select', currentPath.value)
  }
}

onMounted(() => {
  loadDirs()
})
</script>

<style scoped>
.dir-picker-path {
  padding: 10px 15px;
  background: #f5f5f5;
  border-bottom: 1px solid #e0e0e0;
  display: flex;
  align-items: center;
}

.dir-picker-path button {
  padding: 4px 8px;
  border: 1px solid #ccc;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.dir-picker-path button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
