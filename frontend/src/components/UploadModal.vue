<!-- xuechong 2026-06-01 上传进度弹窗组件 -->
<template>
  <Teleport to="body">
    <Transition name="ds-modal">
    <div v-if="visible" class="upload-modal-overlay">
      <div class="upload-modal-dialog">
        <!-- 头部 -->
        <div class="upload-modal-header">
          <div class="upload-modal-title-row">
            <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：弹窗标题栏只留系统logo，
                 原上传功能图标移除 -->
            <img class="dlg-logo" src="../assets/logo-white.png" alt="" />
            <h3>{{ title }}</h3>
          </div>
          <button
            v-if="canCancel"
            class="upload-modal-close"
            @click="$emit('cancel')"
            title="取消上传"
          >✕</button>
        </div>

        <!-- 主体 -->
        <div class="upload-modal-body">
          <!-- 文件夹信息 -->
          <div class="upload-modal-info">
            <div class="upload-info-row">
              <span class="upload-info-label">文件夹</span>
              <span class="upload-info-value">{{ folderName || '—' }}</span>
            </div>
            <div class="upload-info-row">
              <span class="upload-info-label">文件数</span>
              <span class="upload-info-value">{{ totalFiles || 0 }} 个</span>
            </div>
            <div class="upload-info-row">
              <span class="upload-info-label">状态</span>
              <span class="upload-info-value" :class="statusClass">{{ statusText }}</span>
            </div>
          </div>

          <!-- 进度条 -->
          <div class="upload-modal-progress-wrap">
            <div class="upload-modal-progress-text">
              <span>{{ progressMessage }}</span>
            </div>
            <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：进度条与百分比同一行（条左数字右，作为一个整体） -->
            <div class="upload-modal-progress-line">
              <div class="upload-modal-progress-bar">
                <div
                  class="upload-modal-progress-fill"
                  :class="{ 'is-indeterminate': isIndeterminate }"
                  :style="{ width: isIndeterminate ? '100%' : percent + '%' }"
                ></div>
              </div>
              <span v-if="!isIndeterminate" class="upload-modal-progress-percent">{{ percent }}%</span>
            </div>
          </div>

          <!-- 当前文件 -->
          <div v-if="currentFile" class="upload-modal-current-file">
            <span class="current-file-icon"><AppIcon name="file-text" :size="14" /></span>
            <span class="current-file-name">{{ currentFile }}</span>
          </div>
        </div>

        <!-- 底部操作 -->
        <div class="upload-modal-footer">
          <button v-if="isCompleted" class="upload-modal-btn upload-modal-btn-primary" @click="$emit('close')">
            <AppIcon name="check-circle" :size="14" /> 完成
          </button>
          <button v-else-if="isFailed" class="upload-modal-btn upload-modal-btn-danger" @click="$emit('close')">
            <AppIcon name="x" :size="14" /> 关闭
          </button>
          <button v-else-if="canCancel" class="upload-modal-btn upload-modal-btn-cancel" @click="$emit('cancel')">
            {{ isProcessing ? '取消处理' : '取消上传' }}
          </button>
          <span v-if="isUploading" class="upload-modal-elapsed">{{ elapsedText }}</span>
        </div>
      </div>
    </div>
    </Transition>
  </Teleport>
</template>

<script setup>
// xuechong 2026-06-01 上传进度弹窗 — 模态对话框展示上传/处理进度
import { computed } from 'vue'
// xuechong 2026-10-09 研发BUG-0071 图标组件：上传弹窗 emoji 换单色线性 SVG
import AppIcon from './AppIcon.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  title: { type: String, default: '文件上传' },
  folderName: { type: String, default: '' },
  totalFiles: { type: Number, default: 0 },
  percent: { type: Number, default: 0 },
  currentFile: { type: String, default: '' },
  progressMessage: { type: String, default: '' },
  phase: { type: String, default: 'idle' },  // idle | preparing | uploading | processing | completed | failed | cancelled
  elapsed: { type: Number, default: 0 },  // 已用秒数
})

defineEmits(['close', 'cancel'])

// 计算属性
const isUploading = computed(() => props.phase === 'uploading')
const isProcessing = computed(() => props.phase === 'processing')
const isCompleted = computed(() => props.phase === 'completed')
const isFailed = computed(() => props.phase === 'failed' || props.phase === 'cancelled')
const isIndeterminate = computed(() => props.phase === 'preparing')
const canCancel = computed(() => props.phase === 'uploading' || props.phase === 'processing' || props.phase === 'preparing')

const statusText = computed(() => {
  const map = {
    idle: '—',
    preparing: '准备中...',
    uploading: '上传中...',
    processing: '服务器处理中...',
    completed: '✓ 上传完成',
    failed: '✗ 上传失败',
    cancelled: '已取消'
  }
  return map[props.phase] || props.phase
})

const statusClass = computed(() => {
  if (isCompleted.value) return 'status-completed'
  if (isFailed.value) return 'status-failed'
  if (isUploading.value || isProcessing.value || isIndeterminate.value) return 'status-active'
  return ''
})

const elapsedText = computed(() => {
  if (!props.elapsed) return ''
  const m = Math.floor(props.elapsed / 60)
  const s = props.elapsed % 60
  if (m > 0) return `已用 ${m} 分 ${s} 秒`
  return `已用 ${s} 秒`
})
</script>

<style scoped>
/* xuechong 2026-06-01 上传弹窗样式 */
/* xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
   弹框样式统一：头部主色渐变+白字+顶部高光，按钮立体面，配色并入语义色（原 #ff7f00/#ff4d4f 旧色板） */
.upload-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: uploadFadeIn 0.2s ease;
}
@keyframes uploadFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.upload-modal-dialog {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4), 0 4px 12px rgba(0, 0, 0, 0.25);
  width: 480px;
  max-width: 90vw;
  overflow: hidden;
  animation: uploadSlideIn 0.25s ease;
}
@keyframes uploadSlideIn {
  from { transform: translateY(-20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.upload-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 24px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0) 45%),
    linear-gradient(135deg, var(--primary-color, #B3123B) 0%, var(--primary-light, #E63B5F) 100%);
}
.upload-modal-title-row {
  display: flex;
  align-items: center;
  gap: 3px;
}
.upload-modal-icon {
  font-size: 24px;
  color: #fff;
  display: inline-flex;
}
.upload-modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

.upload-modal-body {
  padding: 20px 24px;
}

.upload-modal-info {
  background: #fafafa;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 20px;
}
.upload-info-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 14px;
}
.upload-info-label {
  color: var(--text-secondary, #6B7280);
}
.upload-info-value {
  color: var(--text-primary, #1F2937);
  font-weight: 500;
}
.upload-info-value.status-active {
  color: var(--accent-color, #2563EB);
}
.upload-info-value.status-completed {
  color: var(--success-color, #16A34A);
}
.upload-info-value.status-failed {
  color: var(--error-color, #DC2626);
}

/* 进度条 */
.upload-modal-progress-wrap {
  margin-bottom: 12px;
}
.upload-modal-progress-bar {
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
}
/* xuechong 2026-10-10 研发BUG-0071 用户复验：进度条+百分比同一行（条左数字右一个整体） */
.upload-modal-progress-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.upload-modal-progress-line .upload-modal-progress-bar {
  flex: 1;
}
.upload-modal-progress-percent {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary-color, #B3123B);
  min-width: 38px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.upload-modal-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #B3123B, #E63B5F);
  border-radius: 4px;
  transition: width 0.3s ease;
}
.upload-modal-progress-fill.is-indeterminate {
  animation: uploadIndeterminate 1.5s ease-in-out infinite;
  width: 40% !important;
}
@keyframes uploadIndeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}
.upload-modal-progress-text {
  display: flex;
  font-size: 13px;
  color: var(--text-secondary, #6B7280);
  margin-bottom: 6px;
}

/* 当前文件 */
.upload-modal-current-file {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #FFFBEB;
  border-radius: 6px;
  font-size: 13px;
  color: #B45309;
}
.current-file-icon {
  font-size: 14px;
  display: inline-flex;
}
.current-file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 底部 */
.upload-modal-footer {
  padding: 12px 24px 16px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid #f0f0f0;
}
.upload-modal-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}
.upload-modal-btn-primary {
  background: linear-gradient(180deg, #C9184A 0%, #B3123B 55%, #8E0E2E 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.15);
  color: #fff;
  box-shadow: 0 2px 6px rgba(234, 88, 12, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.upload-modal-btn-primary:hover {
  background: linear-gradient(180deg, #E63B5F 0%, #B3123B 55%, #8E0E2E 100%);
  transform: translateY(-1px);
}
.upload-modal-btn-danger {
  background: #fff;
  color: var(--error-color, #DC2626);
  border: 1px solid var(--error-color, #DC2626);
}
.upload-modal-btn-danger:hover {
  background: var(--error-color, #DC2626);
  color: #fff;
}
.upload-modal-btn-cancel {
  background: #fff;
  color: var(--primary-color, #B3123B);
  border: 1px solid var(--primary-color, #B3123B);
}
.upload-modal-btn-cancel:hover {
  background: var(--primary-light-bg, #FFF1F2);
}
.upload-modal-elapsed {
  font-size: 12px;
  color: var(--text-light, #9CA3AF);
  margin-right: auto;
}
</style>
