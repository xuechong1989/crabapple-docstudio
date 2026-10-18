import { ref, computed } from 'vue'
import * as api from '../api'

/**
 * 编辑PDF — Canvas 绘制、缩放拖拽、撤销/重做、保存/还原
 *
 * 完全自包含，零外部依赖（除了 api 模块）。
 * 从 EditPdfPage.vue 提取而来。
 */
export function useEditPdfCanvas({ showToast, devLog }) {
  // ---- 状态 ----
  const hasChanges = ref(false)
  const canUndo = ref(false)
  const canRedo = ref(false)
  const canRestore = ref(false)
  const scale = ref(1)
  const position = ref({ x: 0, y: 0 })
  const isDragging = ref(false)
  const isDrawing = ref(false)
  const history = ref([])
  const historyIndex = ref(-1)
  const hasDrawn = ref(false)
  const lastDrawPos = ref(null)
  const currentPageUrl = ref('')
  const editedPageUrl = ref('')
  const originalPageUrl = ref('')

  let canvasCtx = null

  // ---- 计算属性 ----
  const imageStyle = computed(() => ({
    transform: `translate(${position.value.x}px, ${position.value.y}px) scale(${scale.value})`
  }))

  const canvasStyle = computed(() => ({
    transform: `translate(-50%, -50%) translate(${position.value.x}px, ${position.value.y}px) scale(${scale.value})`
  }))

  // ---- Canvas 初始化 ----
  function initCanvas(canvasEl, editedImageEl) {
    if (!canvasEl || !editedImageEl) return
    if (!editedImageEl.naturalWidth || !editedImageEl.naturalHeight) return

    canvasEl.width = editedImageEl.naturalWidth
    canvasEl.height = editedImageEl.naturalHeight
    canvasCtx = canvasEl.getContext('2d')
    clearHistory()
  }

  function saveToHistory() {
    const canvas = document.querySelector('.edit-pdf-canvas')
    if (!canvas || !canvasCtx) return
    const imageData = canvasCtx.getImageData(0, 0, canvas.width, canvas.height)

    if (historyIndex.value < history.value.length - 1) {
      history.value = history.value.slice(0, historyIndex.value + 1)
    }
    history.value.push(imageData)
    if (history.value.length > 50) {
      history.value.shift()
    }
    historyIndex.value = history.value.length - 1
  }

  // ---- 绘制（白画笔） ----
  async function startDraw(e, canvasEl) {
    if (!canvasCtx) initCanvas(canvasEl, document.querySelector('.edit-pdf-edited-image'))
    if (!canvasCtx) return

    isDrawing.value = true
    hasDrawn.value = false
    lastDrawPos.value = null
    draw(e, canvasEl)
  }

  function draw(e, canvasEl) {
    if (!isDrawing.value || !canvasCtx || !canvasEl) return

    const canvasRect = canvasEl.getBoundingClientRect()
    if (canvasRect.width === 0 || canvasRect.height === 0) return

    const mouseX = e.clientX - canvasRect.left
    const mouseY = e.clientY - canvasRect.top
    const canvasX = (mouseX / canvasRect.width) * canvasEl.width
    const canvasY = (mouseY / canvasRect.height) * canvasEl.height

    if (canvasX < 0 || canvasX >= canvasEl.width || canvasY < 0 || canvasY >= canvasEl.height) {
      lastDrawPos.value = null
      return
    }

    const ratio = canvasEl.width / canvasRect.width
    const brushRadius = 10 * ratio

    canvasCtx.fillStyle = '#FFFFFF'
    canvasCtx.strokeStyle = '#FFFFFF'
    canvasCtx.lineCap = 'round'
    canvasCtx.lineJoin = 'round'
    canvasCtx.lineWidth = brushRadius * 2

    if (lastDrawPos.value) {
      canvasCtx.beginPath()
      canvasCtx.moveTo(lastDrawPos.value.x, lastDrawPos.value.y)
      canvasCtx.lineTo(canvasX, canvasY)
      canvasCtx.stroke()
    }

    canvasCtx.beginPath()
    canvasCtx.arc(canvasX, canvasY, brushRadius, 0, Math.PI * 2)
    canvasCtx.fill()

    lastDrawPos.value = { x: canvasX, y: canvasY }
    hasDrawn.value = true
    hasChanges.value = true
  }

  function stopDraw() {
    if (isDrawing.value) {
      isDrawing.value = false
      lastDrawPos.value = null
      if (hasDrawn.value) {
        saveToHistory()
        hasDrawn.value = false
      }
    }
  }

  // ---- 撤销/重做 ----
  function undo() {
    if (!canUndo.value || !canvasCtx) return
    historyIndex.value--
    canvasCtx.putImageData(history.value[historyIndex.value], 0, 0)
    if (historyIndex.value === 0) hasChanges.value = false
  }

  function redo() {
    if (!canRedo.value || !canvasCtx) return
    historyIndex.value++
    canvasCtx.putImageData(history.value[historyIndex.value], 0, 0)
    if (historyIndex.value > 0) hasChanges.value = true
  }

  function clearHistory() {
    history.value = []
    historyIndex.value = -1
  }

  // ---- 缩放/拖拽 ----
  function handleWheel(e) {
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    scale.value = Math.max(0.1, Math.min(5, scale.value * delta))
  }

  function startDrag(e) {
    isDragging.value = true
    // 记录起始位置
  }

  function onDrag(e) {
    if (!isDragging.value) return
    position.value = {
      x: position.value.x + e.movementX,
      y: position.value.y + e.movementY
    }
  }

  function stopDrag() {
    isDragging.value = false
  }

  // ---- 保存 ----
  async function save(canvasEl, taskId, fileId, pageNum, ocrLang) {
    if (!canvasEl) {
      showToast?.('画布未初始化', 'error')
      return { success: false }
    }
    try {
      const imageData = canvasEl.toDataURL('image/jpeg', 0.85)
      const response = await api.saveEditPdfPage({
        task_id: taskId,
        file_id: fileId,
        page_num: pageNum,
        image_data: imageData,
        ocr_lang: ocrLang || 'ch'
      })
      const data = response.data
      if (data.success) {
        hasChanges.value = false
        editedPageUrl.value = (data.edited_url || '') + '?t=' + Date.now()
        showToast?.(`保存成功，已识别 ${data.text_count || 0} 个文字块`, 'success')
      } else {
        showToast?.(data.message || '保存失败', 'error')
      }
      return data
    } catch (error) {
      devLog?.('error', '[编辑PDF] 保存失败:', error)
      showToast?.('保存失败: ' + error.message, 'error')
      return { success: false }
    }
  }

  // ---- 还原 ----
  function restore(canvasEl) {
    if (!canvasCtx || !canvasEl) return
    if (history.value.length > 0) {
      historyIndex.value = 0
      canvasCtx.putImageData(history.value[0], 0, 0)
      hasChanges.value = false
      canRestore.value = false
      showToast?.('已还原为原始状态', 'success')
    }
  }

  return {
    // 状态
    hasChanges, canUndo, canRedo, canRestore,
    scale, position, isDragging, isDrawing,
    history, historyIndex, hasDrawn, lastDrawPos,
    currentPageUrl, editedPageUrl, originalPageUrl,
    // 计算属性
    imageStyle, canvasStyle,
    // 函数
    initCanvas, saveToHistory, clearHistory,
    startDraw, draw, stopDraw,
    undo, redo,
    handleWheel, startDrag, onDrag, stopDrag,
    save, restore,
    // 原始 canvasCtx reset
    resetCanvasCtx() { canvasCtx = null }
  }
}
