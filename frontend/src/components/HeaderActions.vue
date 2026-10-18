<template>
  <div class="header-right">
    <button class="version-btn" @click="showVersionModal = true" title="查看系统版本信息和更新日志">
      <AppIcon name="clipboard" :size="13" /> 版本说明
    </button>
    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：操作手册按钮按用户要求全部隐藏（功能代码保留） -->
  </div>

  <VersionModal v-model="showVersionModal" />
</template>

<script setup>
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import VersionModal from './VersionModal.vue'
// xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 下载手册是浏览器直链，嵌入模式下走withEmbedToken拼嵌入参数，否则401
import { withEmbedToken } from '../api'

const showVersionModal = ref(false)

function downloadUserManual() {
  const link = document.createElement('a')
  link.href = withEmbedToken('/api/download-user-manual')
  link.download = '海棠文档工坊_用户操作手册.docx'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}
</script>
