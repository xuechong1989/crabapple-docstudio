<template>
  <div class="log-content" ref="logContainer">
    <div
        v-for="(log, index) in logs"
        :key="index"
        class="log-entry"
        :class="log.level.toLowerCase()"
    >
      <span class="log-time">{{ formatTime(log.timestamp) }}</span>
      <span class="log-level">[{{ log.level }}]</span>
      <span class="log-message">{{ log.message }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  logs: { type: Array, default: () => [] }
})

const logContainer = ref(null)

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

watch(() => props.logs.length, () => {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
})
</script>

<style scoped>
.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  background: #FFFFFF; /* 纯白色背景替代 #1e1e1e */
  color: #333333; /* 深色文字替代 #d4d4d4 */
}

.log-entry {
  padding: 3px 6px;
  margin-bottom: 2px;
  border-radius: 3px;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.log-time {
  color: #6c757d; /* 更柔和的颜色替代 #808080 */
  flex-shrink: 0;
}

.log-level {
  flex-shrink: 0;
  font-weight: bold;
}

.log-entry.info .log-level { color: #0d6efd; } /* 浅色替代深色 */
.log-entry.success .log-level { color: #198754; } /* 浅色替代深色 */
.log-entry.warning .log-level { color: #ffc107; } /* 浅色替代深色 */
.log-entry.error .log-level { color: #dc3545; } /* 浅色替代深色 */

.log-message {
  word-break: break-all;
}
</style>