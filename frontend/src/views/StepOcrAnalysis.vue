<template>
  <div class="itp-right-panel">
    <div class="itp-ocr-page">
      <div class="itp-ocr-header">
        <h3>OCR 文字识别</h3>
        <p>对已修图的图片进行文字识别，生成可搜索的双层PDF</p>
      </div>

      <div class="itp-ocr-actions">
        <button
          class="itp-ocr-btn itp-btn-primary"
          @click="$emit('skip')"
        >
          <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 跳过按钮emoji换单色线性SVG -->
          <AppIcon name="fast-forward" :size="16" /> 跳过此步（与生成PDF合并处理）
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// xuechong 2026-10-09 研发BUG-0071 图标组件：跳过按钮 emoji 换单色线性 SVG
import AppIcon from '../components/AppIcon.vue'

defineEmits(['skip', 'auto-advance'])
</script>
