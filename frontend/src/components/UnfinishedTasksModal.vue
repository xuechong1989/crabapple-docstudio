<template>
  <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
       未完成任务弹框：集中展示未转换完成的任务（等待处理/处理中/已中断），用户主动选择恢复 -->
  <!-- xuechong 2026-10-09 研发BUG-0071 用户复验：移除点击遮罩关闭（浏览任务列表时误点外部
       会整框关掉，恢复入口误关代价高），只保留右上角×与"继续处理"操作关闭 -->
  <Transition name="ds-modal">
  <div v-if="modelValue" class="utm-overlay">
    <div class="utm-modal">
      <div class="utm-header">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 emoji 换单色线性 SVG -->
        <h3><img class="dlg-logo" src="../assets/logo-white.png" alt="" />未完成任务</h3>
        <button class="utm-close" @click="$emit('update:modelValue', false)" title="关闭">&times;</button>
      </div>
      <div class="utm-body">
        <div v-if="tasks.length === 0" class="utm-empty">没有未完成的任务</div>
        <div v-for="task in tasks" :key="task.task_id" class="utm-item">
          <div class="utm-info">
            <div class="utm-name">{{ task.folder_name || task.task_id }}</div>
            <div class="utm-meta">
              <span :class="['utm-status', 'utm-' + statusKey(task)]">{{ statusText(task) }}</span>
              <span>{{ task.total_files }} 个文件</span>
              <span v-if="task.created_at" class="utm-time">{{ formatTime(task.created_at) }}</span>
            </div>
            <div v-if="statusKey(task) === 'interrupted' && task.total_files" class="utm-progress">
              修图进行到 {{ task.clean_processed_files || 0 }}/{{ task.total_files }}，继续处理不会重复已完成的
            </div>
            <div v-else-if="task.message" class="utm-msg">{{ task.message }}</div>
          </div>
          <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：按钮左侧补图标（继续处理=play/查看进度=eye），
               去掉右侧文字箭头→，对齐全站"图标在左"标准 -->
          <!-- xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中"继续处理"会重载
               任务树打断进行中的修图流程，按钮禁用 -->
          <button class="utm-resume" :disabled="actionsLocked" @click="$emit('resume', task)">
            <AppIcon :name="task.status === 'processing' ? 'eye' : 'play'" :size="13" />
            {{ task.status === 'processing' ? '查看进度' : '继续处理' }}
          </button>
        </div>
      </div>
    </div>
  </div>
  </Transition>
</template>

<script setup>
// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 未完成任务弹框：props.tasks 由页面从 composable 传入
// xuechong 2026-10-09 研发BUG-0071 标题图标：emoji 换单色线性 SVG
import AppIcon from './AppIcon.vue'

defineProps({
  modelValue: Boolean,
  tasks: { type: Array, default: () => [] },
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中"继续处理"按钮禁用
  actionsLocked: {
    type: Boolean,
    default: false
  }
})

defineEmits(['update:modelValue', 'resume'])

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 中断判定综合两个状态：
// task.status=interrupted（转换中断）或 clean_status=interrupted（修图中断）都按中断展示
function statusKey(task) {
  if (task.status === 'interrupted' || task.clean_status === 'interrupted') return 'interrupted'
  return task.status || 'unknown'
}

function statusText(task) {
  const key = statusKey(task)
  if (key === 'interrupted') return '已中断'
  const map = {
    uploaded: '等待处理',
    processing: '处理中'
  }
  return map[key] || key
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return iso
  }
}
</script>

<style scoped>
/* xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
   弹框样式统一：头部主色渐变+白字+顶部高光（与版本说明/操作记录弹框同一体系），
   按钮立体面，状态标签配色并入语义色 */
.utm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9500;
}
.utm-modal {
  background: #fff;
  border-radius: 12px;
  width: 560px;
  max-width: 92vw;
  max-height: 78vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4), 0 4px 12px rgba(0, 0, 0, 0.25);
  overflow: hidden;
}
.utm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0) 45%),
    linear-gradient(135deg, var(--primary-color, #EA580C) 0%, var(--primary-light, #F97316) 100%);
}
.utm-header h3 {
  margin: 0;
  font-size: 16px;
  color: #fff;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 3px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}
.utm-body {
  padding: 12px 18px 18px;
  overflow-y: auto;
  flex: 1;
}
.utm-empty {
  text-align: center;
  color: var(--text-light, #9CA3AF);
  padding: 40px 0;
  font-size: 14px;
}
.utm-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 10px;
  border-bottom: 1px solid #f2f2f2;
}
.utm-item:last-child { border-bottom: none; }
.utm-info { flex: 1; min-width: 0; }
.utm-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #1F2937);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.utm-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary, #6B7280);
}
.utm-status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.utm-uploaded { background: #EFF6FF; color: #1D4ED8; }
.utm-processing { background: #FFFBEB; color: #B45309; }
.utm-interrupted { background: #FEF2F2; color: #B91C1C; }
.utm-progress { margin-top: 5px; font-size: 12px; color: #B91C1C; }
.utm-msg { margin-top: 5px; font-size: 12px; color: var(--text-light, #9CA3AF); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.utm-resume {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.15);
  background: linear-gradient(180deg, #F26B1D 0%, #EA580C 55%, #D94E08 100%);
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(234, 88, 12, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.25);
  transition: all 0.15s ease;
}
.utm-resume:hover {
  background: linear-gradient(180deg, #F97B31 0%, #EA580C 55%, #C2410C 100%);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(234, 88, 12, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
/* xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中禁用态灰化 */
.utm-resume:disabled {
  background: #d1d5db;
  color: #f3f4f6;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}
</style>
