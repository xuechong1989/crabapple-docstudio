import { ref, computed, nextTick } from 'vue'

export function useCanvasEditor() {
  // ---- 缩放/拖拽 ----
  const scale = ref(1)
  const offsetX = ref(0)
  const offsetY = ref(0)
  const isDragging = ref(false)
  const dragStart = ref({ x: 0, y: 0 })

  // ---- 绘制 ----
  const isDrawing = ref(false)
  const hasDrawnInSession = ref(false)
  const lastDrawPos = ref(null)
  const hasEdits = ref(false)

  // ---- 撤销/重做 ----
  const editHistory = ref([])
  const historyIndex = ref(-1)
  const maxHistoryLength = 50

  // ---- Canvas 内部状态（非响应式） ----
  let canvasCtx = null
  let imageDrawnOnCanvas = false

  // ---- 计算属性 ----
  const imageStyle = computed(() => ({
    transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`
  }))

  const canvasStyle = computed(() => ({
    transform: `translate(-50%, -50%) translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
    maxWidth: '100%',
    maxHeight: '100%'
  }))

  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value < editHistory.value.length - 1)

  // ---- Canvas DOM 查询 ----
  function getCanvasElements() {
    const canvas = document.querySelector('.edited-panel canvas.edit-canvas')
    const img = document.querySelector('.edited-panel img.preview-image')
    return { canvas, img }
  }

  // ---- Canvas 初始化 ----
  async function initEditCanvas() {
    const { canvas, img } = getCanvasElements()
    if (!canvas || !img) return
    if (!img.naturalWidth || !img.naturalHeight) return

    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight

    const parent = img.parentElement
    if (parent) {
      const pW = parent.clientWidth
      const pH = parent.clientHeight
      const imgAspect = img.naturalWidth / img.naturalHeight
      const parentAspect = pW / pH
      if (imgAspect > parentAspect) {
        canvas.style.width = pW + 'px'
        canvas.style.height = (pW / imgAspect) + 'px'
      } else {
        canvas.style.height = pH + 'px'
        canvas.style.width = (pH * imgAspect) + 'px'
      }
    } else {
      canvas.style.width = img.naturalWidth + 'px'
      canvas.style.height = img.naturalHeight + 'px'
    }

    canvasCtx = canvas.getContext('2d')
    imageDrawnOnCanvas = false
    clearHistory()
  }

  function onCleanedImageLoad() {
    nextTick(() => {
      initEditCanvas()
    })
  }

  function onImageLoad() {}

  // ---- 缩放/拖拽 ----
  function handleWheel(e) {
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    scale.value = Math.max(0.1, Math.min(5, scale.value * delta))
  }

  function startDrag(e) {
    isDragging.value = true
    dragStart.value = {
      x: e.clientX - offsetX.value,
      y: e.clientY - offsetY.value
    }
    document.addEventListener('mousemove', onDragGlobal)
    document.addEventListener('mouseup', stopDragGlobal)
  }

  function onDrag(e) {
    if (!isDragging.value) return
    offsetX.value = e.clientX - dragStart.value.x
    offsetY.value = e.clientY - dragStart.value.y
  }

  function onDragGlobal(e) {
    if (!isDragging.value) return
    offsetX.value = e.clientX - dragStart.value.x
    offsetY.value = e.clientY - dragStart.value.y
  }

  function stopDrag() {
    isDragging.value = false
    document.removeEventListener('mousemove', onDragGlobal)
    document.removeEventListener('mouseup', stopDragGlobal)
  }

  function stopDragGlobal() {
    isDragging.value = false
    document.removeEventListener('mousemove', onDragGlobal)
    document.removeEventListener('mouseup', stopDragGlobal)
  }

  // ---- 手动修图绘制 ----
  async function startDraw(e) {
    if (!canvasCtx) await initEditCanvas()
    if (!canvasCtx) return

    if (!imageDrawnOnCanvas) {
      const { img } = getCanvasElements()
      if (img) {
        await img.decode()
        canvasCtx.drawImage(img, 0, 0)
        imageDrawnOnCanvas = true
        saveToHistory()
      }
    }

    isDrawing.value = true
    hasDrawnInSession.value = false
    lastDrawPos.value = null
    draw(e)
  }

  function draw(e) {
    if (!isDrawing.value || !canvasCtx) return
    const { canvas } = getCanvasElements()
    if (!canvas) return

    const canvasRect = canvas.getBoundingClientRect()
    if (canvasRect.width === 0 || canvasRect.height === 0) return

    const mouseX = e.clientX - canvasRect.left
    const mouseY = e.clientY - canvasRect.top
    const canvasX = (mouseX / canvasRect.width) * canvas.width
    const canvasY = (mouseY / canvasRect.height) * canvas.height

    if (canvasX < 0 || canvasX >= canvas.width || canvasY < 0 || canvasY >= canvas.height) {
      lastDrawPos.value = null
      return
    }

    const displayToCanvasRatio = canvas.width / canvasRect.width
    const brushRadius = 10 * displayToCanvasRatio

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
    hasDrawnInSession.value = true

    if (!hasEdits.value) {
      hasEdits.value = true
    }
  }

  function stopDraw() {
    if (isDrawing.value) {
      isDrawing.value = false
      lastDrawPos.value = null
      if (hasDrawnInSession.value) {
        saveToHistory()
        hasDrawnInSession.value = false
      }
    }
  }

  // ---- 撤销/重做 ----
  function saveToHistory() {
    const { canvas } = getCanvasElements()
    if (!canvas || !canvasCtx) return
    const imageData = canvasCtx.getImageData(0, 0, canvas.width, canvas.height)

    if (historyIndex.value < editHistory.value.length - 1) {
      editHistory.value = editHistory.value.slice(0, historyIndex.value + 1)
    }

    editHistory.value.push(imageData)

    if (editHistory.value.length > maxHistoryLength) {
      editHistory.value.shift()
    }
    historyIndex.value = editHistory.value.length - 1
  }

  function undoEdit() {
    if (!canUndo.value || !canvasCtx) return
    historyIndex.value--
    const imageData = editHistory.value[historyIndex.value]
    canvasCtx.putImageData(imageData, 0, 0)
    if (historyIndex.value === 0) hasEdits.value = false
  }

  function redoEdit() {
    if (!canRedo.value || !canvasCtx) return
    historyIndex.value++
    const imageData = editHistory.value[historyIndex.value]
    canvasCtx.putImageData(imageData, 0, 0)
    if (historyIndex.value > 0) hasEdits.value = true
  }

  function clearHistory() {
    editHistory.value = []
    historyIndex.value = -1
  }

  function resetCanvasCtx() {
    canvasCtx = null
    imageDrawnOnCanvas = false
  }

  return {
    // 状态
    scale, offsetX, offsetY, isDragging, dragStart,
    isDrawing, hasDrawnInSession, lastDrawPos,
    hasEdits,
    editHistory, historyIndex, maxHistoryLength,
    // 计算属性
    imageStyle, canvasStyle, canUndo, canRedo,
    // 函数
    getCanvasElements, initEditCanvas, onCleanedImageLoad, onImageLoad,
    handleWheel, startDrag, onDrag, stopDrag,
    startDraw, draw, stopDraw,
    saveToHistory, undoEdit, redoEdit, clearHistory,
    resetCanvasCtx
  }
}
