<template>
  <div class="itp-right-panel">
    <div class="itp-generate-page">
      <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态 -->
      <!-- 递归批量修图完成后 PDF 已全部自动生成，显示完成视图引导预览/下载（替代误导性的"生成PDF"按钮） -->
      <template v-if="batchCompleteInfo && !isProcessing">
        <div class="itp-generate-complete">
          <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 本页emoji换单色线性SVG -->
          <div class="success-icon"><AppIcon name="check-circle" :size="48" /></div>
          <h3>全部完成</h3>
          <p>{{ batchCompleteInfo.folders }} 个文件夹已自动完成修图并生成 PDF</p>
          <div class="itp-generate-actions" style="margin-top: 16px;">
            <button
              class="itp-generate-btn itp-btn-orange"
              @click="$emit('open-history')"
            >
              <AppIcon name="clipboard" :size="16" /> 打开转换记录
            </button>
          </div>
        </div>
      </template>

      <!-- 生成前 -->
      <template v-else-if="!isProcessing && !showDownloadBtn">
        <div class="itp-generate-header">
          <h3><AppIcon name="file-text" :size="18" /> 生成PDF</h3>
        </div>
        <div class="itp-generate-actions">
          <button
            class="itp-generate-btn itp-btn-orange"
            :disabled="!canProcess"
            @click="$emit('generate')"
          >
            <AppIcon name="zap" :size="16" /> 生成PDF
          </button>
          <button
            class="itp-generate-btn itp-btn-orange-light"
            @click="$emit('open-history')"
          >
            <AppIcon name="clipboard" :size="16" /> 转换记录
          </button>
        </div>
      </template>

      <!-- 生成中 -->
      <template v-else-if="isProcessing">
        <div class="itp-generate-header">
          <h3><AppIcon name="hourglass" :size="18" /> 正在生成PDF...</h3>
          <p>{{ statusMessage }}</p>
        </div>
        <div class="itp-generate-progress">
          <div class="itp-progress-bar" style="height: 8px;">
            <div
              class="itp-progress-fill animated"
              :style="{ width: progress + '%' }"
            ></div>
          </div>
          <div class="itp-progress-info" style="margin-top: 8px;">
            <span><AppIcon name="clock" :size="14" /> {{ formatTime(processElapsed) }}</span>
            <span>{{ progress }}%</span>
          </div>
        </div>
      </template>

      <!-- 生成完成 -->
      <template v-else-if="showDownloadBtn">
        <div class="itp-generate-complete">
          <div class="success-icon"><AppIcon name="check-circle" :size="48" /></div>
          <p>{{ statusMessage }}</p>
          <div class="itp-generate-actions">
            <button class="itp-btn itp-btn-orange" @click="$emit('preview-pdf')"><AppIcon name="eye" :size="14" /> 预览PDF</button>
            <button class="itp-btn itp-btn-orange" @click="$emit('download-pdf')"><AppIcon name="download" :size="14" /> 下载PDF</button>
            <button class="itp-btn itp-btn-blue" @click="$emit('edit-pdf')"><AppIcon name="edit" :size="14" /> 编辑PDF</button>
            <button class="itp-btn itp-btn-orange-light" @click="$emit('open-history')"><AppIcon name="clipboard" :size="14" /> 转换记录</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态修复
// batchCompleteInfo：递归批量修图完成摘要 { folders: N }，有值时显示批量完成视图
// xuechong 2026-10-09 研发BUG-0071 图标组件：本步骤页 emoji 换单色线性 SVG
import AppIcon from '../components/AppIcon.vue'

defineProps({
  canProcess: Boolean,
  isProcessing: Boolean,
  showDownloadBtn: Boolean,
  statusMessage: String,
  progress: Number,
  processElapsed: Number,
  formatTime: Function,
  batchCompleteInfo: Object
})

defineEmits(['generate', 'preview-pdf', 'download-pdf', 'edit-pdf', 'open-history'])
</script>
