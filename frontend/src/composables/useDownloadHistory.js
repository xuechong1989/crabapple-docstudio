import { ref, computed } from 'vue'
import * as api from '../api'

export function useDownloadHistory() {
  const downloadHistory = ref([])
  const historyCurrentPage = ref(1)
  const historyPageSize = ref(10)

  const historyTotalPages = computed(() =>
    Math.ceil(downloadHistory.value.length / historyPageSize.value) || 1
  )

  const paginatedHistory = computed(() => {
    const start = (historyCurrentPage.value - 1) * historyPageSize.value
    const end = start + historyPageSize.value
    return downloadHistory.value.slice(start, end)
  })

  function formatElapsedTime(seconds) {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0')
  }

  async function loadDownloadHistory() {
    try {
      const response = await api.getDownloadHistory()
      downloadHistory.value = response.data || []
    } catch (e) {
      console.warn('[下载历史] 加载失败:', e)
    }
  }

  async function deleteHistoryItem(index) {
    try {
      await api.deleteDownloadHistoryItem(index)
      downloadHistory.value.splice(index, 1)
      if (historyCurrentPage.value > historyTotalPages.value) {
        historyCurrentPage.value = Math.max(1, historyTotalPages.value)
      }
    } catch (e) {
      console.warn('[下载历史] 删除失败:', e)
    }
  }

  return {
    downloadHistory, historyCurrentPage, historyPageSize,
    historyTotalPages, paginatedHistory,
    formatElapsedTime,
    loadDownloadHistory, deleteHistoryItem
  }
}
