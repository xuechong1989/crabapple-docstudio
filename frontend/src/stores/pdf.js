import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePdfStore = defineStore('pdf', () => {
  // 待编辑的 PDF 信息
  const pendingEdit = ref(null)

  // 设置待编辑 PDF（从其他模块跳转过来时调用）
  function setPendingEdit({ source, pdfPath, task_id, fileName, history_index }) {
    pendingEdit.value = { source, pdfPath, task_id, fileName, history_index }
  }

  // 清除待编辑 PDF（编辑页处理完后调用）
  function clearPendingEdit() {
    pendingEdit.value = null
  }

  return { pendingEdit, setPendingEdit, clearPendingEdit }
})
