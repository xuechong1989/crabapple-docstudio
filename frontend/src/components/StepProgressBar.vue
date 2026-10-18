<template>
  <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：模式+上传下拉迁入左栏卡内顶部（与文件树连成
       一张卡、灰色分割线分开，同编辑PDF结构）；步骤条本行通栏（步骤卡与下方内容行同宽） -->
  <div class="itp-process-bar">
    <!-- 步骤项 -->
    <div class="itp-steps-wrapper">
      <div
        v-for="(step, index) in steps"
        :key="step.num"
        class="itp-step compact"
        :class="{
          active: stepStatus[step.num] === 'active',
          completed: stepStatus[step.num] === 'completed',
          pending: stepStatus[step.num] === 'pending',
          clickable: step.num !== 1 && !isAutoMode && !isProcessing,
          processing: stepStatus[step.num] === 'active' && isProcessing
        }"
        @click="step.num !== 1 && !isAutoMode && !isProcessing && $emit('go-to-step', step.num)"
      >
        <div class="itp-step-tip">{{ step.tip }}</div>
        <div class="itp-step-icon">
          <span v-if="stepStatus[step.num] === 'completed'">&#10003;</span>
          <span v-else>{{ index + 1 }}</span>
        </div>
        <div class="itp-step-text">{{ step.label }}</div>
        <div v-if="stepStatus[step.num] === 'active'" class="itp-step-indicator"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
// xuechong 2026-10-10 研发BUG-0071 模式下拉迁至左栏后本组件只负责步骤条；
// isAutoMode 用于控制步骤可点击，其余 props 保留兼容
defineProps({
  stepStatus: {
    type: Object,
    required: true
  },
  operationMode: {
    type: String,
    default: 'auto'
  },
  isAutoMode: {
    type: Boolean,
    default: false
  },
  lockAutoMode: {
    type: Boolean,
    default: false
  },
  // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
  // 处理中（净化/OCR/合成）当前步骤圆圈外围显示旋转光环（loading动效，用户复验要求）
  isProcessing: {
    type: Boolean,
    default: false
  }
})

defineEmits(['go-to-step', 'update:operationMode'])

// xuechong 2026-10-11 研发BUG-0073 修图锁定：处理中步骤条锁定不可点（clickable 类不挂，
// 光标转常规；页面 handleStepClick 内另有兜底拦截）

const steps = [
  { num: 1, label: '扫描/导入', tip: '点击上传按钮导入图片/文件夹' },
  { num: 2, label: '修图净化', tip: '点击一键修图自动优化图片质量' },
  { num: 4, label: '生成PDF', tip: '生成可搜索/压缩的PDF文件' }
]
</script>
