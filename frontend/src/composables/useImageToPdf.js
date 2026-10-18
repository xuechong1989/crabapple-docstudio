import { ref, computed, nextTick, watch, onUnmounted } from 'vue'
import * as api from '../api'
import { useToast } from './useToast'

const isDev = import.meta.env.DEV
function devLog(level, ...args) { if (isDev) console[level](...args) }

export function useImageToPdf() {
  const { showToast, showErrorModal } = useToast()

  // ============================================================
  // 步骤流程状态
  // ============================================================
  const currentStep = ref(1)  // 1-4
  const stepStatus = ref({ 1: 'active', 2: 'pending', 4: 'pending' })

  // 操作模式：'auto' | 'manual'
  const operationMode = ref('manual')
  // 手动模式下的活跃工具面板
  const manualActivePanel = ref('clean')  // 'clean' | 'ocr' | 'generate'

  function goToStep(n) {
    if (n === 3) n = 4  // OCR步骤已移除，重定向到生成PDF
    if (n < 1 || n > 4) return
    // 只能跳到已完成的步骤或当前步骤
    for (let i = 1; i < n; i++) {
      if (i === 3) continue  // 跳过已移除的OCR步骤
      if (stepStatus.value[i] !== 'completed') return
    }
    currentStep.value = n
    const newStatus = { ...stepStatus.value }
    for (const s of [1, 2, 4]) {
      if (s < n) newStatus[s] = 'completed'
      else if (s === n) newStatus[s] = 'active'
      else newStatus[s] = 'pending'
    }
    stepStatus.value = newStatus
  }

  function advanceStep() {
    // 从步骤2直接跳到步骤4（跳过已移除的OCR步骤3）
    const next = currentStep.value === 2 ? 4 : currentStep.value + 1
    if (next > 4) return
    const newStatus = { ...stepStatus.value }
    newStatus[currentStep.value] = 'completed'
    newStatus[next] = 'active'
    stepStatus.value = newStatus
    currentStep.value = next

    // 自动模式：自动推进后续步骤
    if (operationMode.value === 'auto') {
      autoAdvanceFromStep(next)
    }
  }

  async function autoAdvanceFromStep(step) {
    if (step === 2) {
      // 自动触发批量修图，完成后自动进入步骤4（跳过OCR）
      await startBatchCleanAuto()
    } else if (step === 4) {
      // 自动触发PDF生成
      await startProcessAuto()
    }
  }

  // 自动模式：从当前步骤开始全自动执行
  async function startAutoProcess() {
    if (!currentTask.value) return
    const node = effectiveDirectoryNode.value
    if (!node) return

    // 直接设置步骤状态，跳过 goToStep 的前置步骤完成检查
    stepStatus.value = { 1: 'completed', 2: 'active', 4: 'pending' }
    currentStep.value = 2

    if (hasSubDirectories(node)) {
      // 包含子目录：自动扫描基层目录，逐个处理（清理+生成PDF）
      const leafDirs = getAllLeafDirectories(node)
      if (leafDirs.length === 0) {
        showToast('选中的目录下没有可处理的图片文件夹', 'warning')
        return
      }
      await processAutoBatchDirectories(leafDirs)
    } else {
      // 叶基层目录：走批量修图 → 生成PDF
      await autoAdvanceFromStep(2)
    }
  }

  // 自动模式：批量处理多个基层目录（包含子目录的场景）
  async function processAutoBatchDirectories(leafDirs) {
    const processList = [...leafDirs]

    isBatchPdfProcessing.value = true
    showBatchPdfProgressModal.value = true
    batchPdfProgress.value = {
      current: 0, total: processList.length, currentFolder: '', currentProgress: 0, currentMessage: '', status: 'processing'
    }

    showToast(`开始自动处理 ${processList.length} 个文件夹`, 'info')

    try {
      for (let i = 0; i < processList.length; i++) {
        if (!currentTask.value) break
        const item = processList[i]
        batchPdfProgress.value.current = i
        batchPdfProgress.value.currentFolder = item.name
        batchPdfProgress.value.currentProgress = 0
        batchPdfProgress.value.currentMessage = '准备处理...'

        try {
          // xuechong 2026-09-29 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
          // 自动链生成PDF固定不带页码（需求§5.1：生成环节不带页码，页码在form-in步骤7智能组卷环节添加，避免双重页码）
          const res = await processUploadWithBusyRetry(currentTask.value.task_id, pageNoParam(false), item.path)  // 研发BUG-0074：默认模式听复选框，嵌入模式保持不加
          if (res.data.already_completed) {
            batchPdfProgress.value.currentProgress = 100
            batchPdfProgress.value.currentMessage = '已完成（跳过）'
            batchPdfProgress.value.current = i + 1
            continue
          }
          await waitForProcessCompleteWithProgress()
          batchPdfProgress.value.current = i + 1
        } catch (err) {
          showErrorModal(`${item.name} 处理失败`, err.response?.data?.detail || err.message)
          batchPdfProgress.value.status = 'failed'
          isBatchPdfProcessing.value = false
          return
        }
      }

      batchPdfProgress.value.status = 'completed'
      isBatchPdfProcessing.value = false
      showToast(`自动处理完成！共处理 ${processList.length} 个文件夹，请在'转换记录'中下载`, 'success')
      stepStatus.value = { 1: 'completed', 2: 'completed', 4: 'completed' }

      if (currentTask.value?.task_id) {
        await loadFileTree(currentTask.value.task_id)
      }
      await loadDownloadHistory()
      // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
      // 批量全自动完成口径（与startRecursiveBatchClean一致）：不停在进度弹窗等用户点"关闭"，
      // 直接收起进度弹窗并弹出转换记录供预览下载（batchGenerateSummary驱动页面级watch打开）
      showBatchPdfProgressModal.value = false
      batchGenerateSummary.value = { folders: processList.length }
    } catch (err) {
      devLog('error', '[自动处理] 处理异常:', err)
      batchPdfProgress.value.status = 'failed'
      batchPdfProgress.value.currentMessage = '处理异常: ' + (err?.response?.data?.detail || err.message || '未知错误')
      isBatchPdfProcessing.value = false
      showErrorModal('自动处理异常', err?.response?.data?.detail || err.message || '未知错误')
    }
  }

  async function startBatchCleanAuto() {
    if (!currentTask.value) return
    const dirPath = effectiveDirectoryPath.value
    const node = effectiveDirectoryNode.value
    if (!node || node.type !== 'directory') return

    // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    // 上传完成后自动选中的是文件树根节点（后端build_tree根目录path为空字符串），根节点/含子目录的
    // 目录不能直接下发batch-clean（后端按"请选择要处理的目录"拒绝空路径，且修图按目录粒度执行）：
    // 有子目录时按基层目录逐个"一键修图→生成PDF"（与startAutoProcess多目录口径一致），
    // 只有基层目录才走单目录修图轮询
    if (hasSubDirectories(node)) {
      const leafDirs = getAllLeafDirectories(node)
      if (leafDirs.length > 0) {
        await processAutoBatchDirectories(leafDirs)
      }
      return
    }
    if (!dirPath) return

    batchCleanOriginalDirPath = dirPath

    try {
      const res = await api.batchClean(currentTask.value.task_id, dirPath)
      if (res.data.success) {
        isBatchCleaning.value = true
        showBatchCleanProgress.value = true
        batchCleanElapsed.value = 0
        // 轮询完成后自动 advanceStep
        startBatchCleanPollingAuto()
        startBatchCleanTimer()
      }
    } catch (err) {
      showToast('自动修图失败: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms，避免CPU密集处理时网络抖动导致轮询中断
  function startBatchCleanPollingAuto() {
    if (batchCleanTimer.value) clearInterval(batchCleanTimer.value)
    let lastProcessedCount = 0
    // xuechong 2026-07-03 网络错误重试计数，连续失败3次才停止轮询
    let retryCount = 0
    const MAX_RETRIES = 3

    batchCleanTimer.value = setInterval(async () => {
      if (!currentTask.value) {
        stopBatchCleanPolling()
        return
      }
      try {
        const res = await api.getBatchCleanStatus(currentTask.value.task_id)
        // xuechong 2026-07-03 请求成功后重置重试计数
        retryCount = 0
        batchCleanStatus.value = res.data

        const processedCount = res.data.processed_files || 0
        if (res.data.current_path && processedCount > lastProcessedCount && res.data.status === 'processing') {
          lastProcessedCount = processedCount
          await updateBatchCleanPreview(res.data.current_path)
        }

        // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        // idle 终止：服务重启后内存态丢失返回idle，停止轮询并引导从未完成任务恢复
        if (res.data.status === 'idle') {
          stopBatchCleanPolling()
          stopBatchCleanTimer()
          isBatchCleaning.value = false
          showToast('修图状态丢失（服务可能已重启），请点击右上角"未完成任务"恢复续跑', 'warning')
          return
        }

        if (['completed', 'failed', 'cancelled'].includes(res.data.status)) {
          stopBatchCleanPolling()
          stopBatchCleanTimer()
          isBatchCleaning.value = false

          if (batchCleanOriginalDirPath) {
            selectedPath.value = batchCleanOriginalDirPath
          }

          if (res.data.status === 'completed') {
            showToast('自动修图完成！', 'success')
            if (currentFilePath.value) {
              const timestamp = Date.now()
              originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
              previewUrl.value = originalPreviewUrl.value
              cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
            }
            // 自动进入步骤3 (OCR)
            advanceStep()
          } else if (res.data.status === 'cancelled') {
            showToast(res.data.message || '修图已停止', 'info')
          } else {
            showToast('自动修图失败: ' + res.data.message, 'error')
          }
        }
      } catch (err) {
        retryCount++
        devLog('error', '[自动修图] 轮询失败 (第' + retryCount + '次):', err)
        // xuechong 2026-07-03 连续失败才停止，容忍瞬时网络抖动
        if (retryCount >= MAX_RETRIES) {
          stopBatchCleanPolling()
          showErrorModal('自动修图轮询异常', '连续' + MAX_RETRIES + '次网络异常，已停止轮询，请检查服务状态')
        }
      }
    }, 5000)
  }

  async function startProcessAuto() {
    if (!currentTask.value) return
    const dirPath = effectiveDirectoryPath.value
    const node = effectiveDirectoryNode.value
    if (!node) return

    if (!isLeafDirectory(node)) {
      const hasSubDirs = node.children?.some(child => child.type === 'directory')
      if (hasSubDirs) {
        const leafDirs = getAllLeafDirectories(node)
        if (leafDirs.length > 0) {
          // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
          // 自动模式（无人值守）检测到子文件夹时不弹"批量生成PDF"确认框，直接按基层目录
          // 逐个生成（进度在批量进度弹窗展示）；手动模式仍走 startProcess 的确认弹窗，两模式互不影响
          await processAutoBatchDirectories(leafDirs)
          return
        }
      }
      return
    }

    await processSingleDirectory(dirPath, node.name)
  }

  function goBack() {
    if (currentStep.value > 1) {
      goToStep(currentStep.value - 1)
    }
  }

  function resetSteps() {
    currentStep.value = 1
    stepStatus.value = { 1: 'active', 2: 'pending', 4: 'pending' }
  }

  // 切换步骤时重置 canvas 上下文（避免指向已销毁的 canvas 元素）
  watch(currentStep, () => {
    canvasCtx = null
  })

  // ============================================================
  // 模板引用
  // ============================================================
  const folderInput = ref(null)
  const leftContainer = ref(null)
  const rightContainer = ref(null)

  // ============================================================
  // 核心状态
  // ============================================================
  const currentTask = ref(null)
  const fileTree = ref({ name: '', type: 'directory', children: [] })
  const selectedPath = ref('')
  const expandedPaths = ref(new Set())
  const showDeleteConfirm = ref(false)
  const previewUrl = ref('')
  // xuechong 2026-08-27 研发需求-0138-图档扫描-3.2.00-PDF添加页码 默认开启：每页底部居中添加页码（宋体/黑色/10号字，从1开始）
  // xuechong 2026-10-11 研发BUG-0074-图档扫描-3.3.03-图片转PDF模块添加页码选项
  // 3.3.02 及之前页码行为按链路分裂（单文件夹加、批量链不加且无界面开关），本版统一：
  // 系统默认模式所有生成链路听界面"添加页码"复选框（默认勾选）；嵌入模式（form-in）保持历史行为一字不动
  const addPageNumber = ref(true)
  // 嵌入模式标记（与页面组件 ImageToPdfPage 同一 sessionStorage 来源）
  const EMBED_MODE = sessionStorage.getItem('ds_embed_mode') === '1'
  /**
   * 生成PDF的页码参数统一出口（研发BUG-0074）。
   * @param {boolean} legacyValue 该调用点在 3.3.02 的历史行为（嵌入模式原样返回，保证 form-in 链路零变化）；
   *                              系统默认模式一律返回界面复选框状态，消灭链路间不一致
   */
  function pageNoParam(legacyValue) {
    return EMBED_MODE ? legacyValue : addPageNumber.value
  }
  const pollTimer = ref(null)
  const isUploading = ref(false)
  const abortController = ref(null)  // xuechong 2026-06-01 用于取消上传请求

  // xuechong 2026-06-01 上传弹窗状态
  const showUploadModal = ref(false)
  const uploadModalTitle = ref('文件上传')
  const uploadModalPhase = ref('idle')  // idle | preparing | uploading | processing | completed | failed | cancelled
  const uploadModalCurrentFile = ref('')
  const uploadModalElapsed = ref(0)
  const uploadModalFolderName = ref('')  // xuechong 2026-06-03 上传中文件夹名（currentTask尚未设置时用）
  const uploadModalTotalFiles = ref(0)   // xuechong 2026-06-03 上传中文件总数
  let _uploadElapsedTimer = null

  function _startUploadTimer() {
    _stopUploadTimer()
    uploadModalElapsed.value = 0
    _uploadElapsedTimer = setInterval(() => { uploadModalElapsed.value++ }, 1000)
  }
  function _stopUploadTimer() {
    if (_uploadElapsedTimer) { clearInterval(_uploadElapsedTimer); _uploadElapsedTimer = null }
  }

  // ============================================================
  // 上传进度
  // ============================================================
  const uploadProgress = ref({
    visible: false,
    current: 0,
    total: 0,
    percent: 0,
    uploading: false,
    message: ''
  })

  // ============================================================
  // 图片修图相关状态
  // ============================================================
  const originalPreviewUrl = ref('')
  const cleanedPreviewUrl = ref('')
  const isLoadingCleaned = ref(false)
  const hasEdits = ref(false)
  const canRestore = ref(false)
  const showLoading = ref(false)
  const loadingMessage = ref('')
  const showRestoreConfirm = ref(false)
  const currentFilePath = ref('')

  // 图片导航
  const siblingImages = ref([])
  const currentImageIndex = ref(-1)

  // 旋转
  const isRotating = ref(false)

  // 未保存修改提示
  const showUnsavedWarning = ref(false)
  const pendingAction = ref(null)
  const pendingUploadFiles = ref(null)

  // 替换确认（已有任务时上传新文件夹）
  const showReplaceConfirm = ref(false)
  const pendingReplaceFiles = ref(null)

  // 图片变换（缩放/拖拽）
  const scale = ref(1)
  const offsetX = ref(0)
  const offsetY = ref(0)
  const isDragging = ref(false)
  const dragStart = ref({ x: 0, y: 0 })

  // 绘图
  const isDrawing = ref(false)
  const hasDrawnInSession = ref(false)
  const lastDrawPos = ref(null)

  // 撤销/重做
  const editHistory = ref([])
  const historyIndex = ref(-1)
  const maxHistoryLength = 50
  let canvasCtx = null
  let imageDrawnOnCanvas = false

  // ============================================================
  // 一键修图相关状态
  // ============================================================
  const isBatchCleaning = ref(false)
  const showBatchCleanProgress = ref(false)
  const showBatchCleanConfirmModal = ref(false)
  const batchCleanStatus = ref({
    status: 'idle',
    progress: 0,
    current_file: '',
    current_path: '',
    message: '',
    images_cleaned: false
  })
  const batchCleanTimer = ref(null)
  const batchCleanElapsedTimer = ref(null)
  const batchCleanElapsed = ref(0)
  let batchCleanOriginalDirPath = ''

  // 递归批量修图状态（一级文件夹包含多个子文件夹场景）
  const recursiveCleanQueue = ref([])  // 待处理的叶目录队列
  // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
  // 单文件夹一键修图自动生成PDF的挂起标记：修图完成时置true，PDF生成轮询完成时
  // 消费为批量完成摘要（folders:1），使单文件夹与递归批量的结束视图同口径
  // xuechong 2026-10-11 研发BUG-0073 ref化并纳入修图锁定：单文件夹修图完成后到PDF生成
  // 状态被轮询感知之间有数秒空窗，布尔标记全程覆盖修图→自动生成→完成，锁定无间隙
  const batchCleanAutoGenPending = ref(false)
  const recursiveCleanIndex = ref(0)   // 当前处理到的索引
  const recursiveCleanTotal = ref(0)   // 总目录数

  // ============================================================
  // 图片重绘相关状态
  // ============================================================
  const isRedrawing = ref(false)
  const redrawStep = ref(10)
  const isBatchRedrawing = ref(false)
  const showBatchRedrawProgress = ref(false)
  const batchRedrawStatus = ref({
    status: 'idle',
    progress: 0,
    current_file: '',
    message: ''
  })
  const batchRedrawTimer = ref(null)
  const batchRedrawElapsedTimer = ref(null)
  const batchRedrawElapsed = ref(0)
  const showRedrawSettings = ref(false)
  let batchRedrawOriginalDirPath = ''

  // ============================================================
  // 批量生成PDF相关状态
  // ============================================================
  const showBatchPdfModal = ref(false)
  const showBatchPdfProgressModal = ref(false)
  const batchPdfList = ref([])
  const isBatchPdfProcessing = ref(false)
  const batchPdfProgress = ref({
    current: 0,
    total: 0,
    currentFolder: '',
    currentProgress: 0,
    currentMessage: '',
    status: 'idle'
  })

  // 处理计时器
  const processTimer = ref(null)
  const processElapsed = ref(0)

  // 下载按钮
  const showDownloadBtn = ref(false)

  // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态修复
  // 递归批量修图完成后 PDF 已全部自动生成，但界面落在"生成PDF"按钮前，用户误以为还需手动点击。
  // 此状态标记批量完成事实，驱动 StepGeneratePdf 显示批量完成视图（打开转换记录预览/下载）；
  // 单目录流程不受影响（保持 null 走原"生成前/完成"逻辑）
  const batchGenerateSummary = ref(null)

  // 生成记录分页
  const historyCurrentPage = ref(1)
  const historyPageSize = ref(10)
  const downloadHistory = ref([])
  const uploadHistory = ref([])  // xuechong 2026-06-01 上传历史记录

  // ============================================================
  // 计算属性
  // ============================================================
  const imageStyle = computed(() => ({
    transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`
  }))

  const isProcessing = computed(() => currentTask.value?.status === 'processing')
  const isBusy = computed(() => isUploading.value || isProcessing.value || isBatchCleaning.value || isBatchPdfProcessing.value || isBatchRedrawing.value)
  // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
  // 修图锁定：一键修图/批量一键修图（递归）/批量重绘进行中，页面只保留查看类操作
  // （预览、下载、记录查看、图片切换、缩放），其余修改类操作全部禁用，处理完成后自动恢复。
  // 口径与用户要求一致（修图期间），上传中/生成PDF处理中的禁用仍走既有 isBusy 口径，不扩大
  const cleaningLocked = computed(() => isBatchCleaning.value || isBatchRedrawing.value || batchCleanAutoGenPending.value)

  const historyTotalPages = computed(() => Math.ceil(downloadHistory.value.length / historyPageSize.value) || 1)
  const paginatedHistory = computed(() => {
    const start = (historyCurrentPage.value - 1) * historyPageSize.value
    const end = start + historyPageSize.value
    return downloadHistory.value.slice(start, end)
  })

  // 文件树节点查找
  const selectedNode = computed(() => {
    if (selectedPath.value === null || selectedPath.value === undefined || !fileTree.value) return null
    return findNodeByPath(fileTree.value, selectedPath.value)
  })

  const effectiveDirectoryPath = computed(() => {
    const node = selectedNode.value
    if (!node) return ''
    if (node.type === 'directory') return node.path
    const path = node.path
    const lastSlash = path.lastIndexOf('/')
    if (lastSlash > 0) {
      return path.substring(0, lastSlash)
    } else {
      // V3.1.01 xuechong 2026-07-25 修复：根目录下的文件，父目录是根节点（path 为空字符串，不是 '.'）
      return ''
    }
  })

  const effectiveDirectoryNode = computed(() => {
    const path = effectiveDirectoryPath.value
    if (path === null || path === undefined || !fileTree.value) return null
    return findNodeByPath(fileTree.value, path)
  })

  const canProcess = computed(() => {
    if (isBusy.value) return false
    if (!currentTask.value) return false
    if (currentTask.value.status !== 'uploaded' && currentTask.value.status !== 'completed') return false
    if (currentTask.value.total_files <= 0) return false
    const node = effectiveDirectoryNode.value
    if (!node || node.type !== 'directory') return false
    return isLeafDirectory(node) || hasSubDirectories(node)
  })

  const canSingleClean = computed(() => {
    return !!currentTask.value && !!currentFilePath.value && !isBusy.value && !isBatchCleaning.value
  })

  const canBatchClean = computed(() => {
    if (!currentTask.value || isBusy.value) return false
    if (!selectedPath.value) return false
    const node = effectiveDirectoryNode.value
    if (!node || node.type !== 'directory') return false
    return isLeafDirectory(node) || hasSubDirectories(node)
  })

  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value < editHistory.value.length - 1)

  const canGoPrev = computed(() => currentImageIndex.value > 0)
  const canGoNext = computed(() => currentImageIndex.value < siblingImages.value.length - 1)

  // ============================================================
  // 文件树工具函数
  // ============================================================
  function findNodeByPath(tree, path) {
    if (!tree) return null
    if (tree.path === path) return tree
    if (tree.children) {
      for (const child of tree.children) {
        const found = findNodeByPath(child, path)
        if (found) return found
      }
    }
    return null
  }

  function findFirstImage(node) {
    if (!node) return null
    const imageExtensions = /\.(jpg|jpeg|png|tif|tiff|bmp|webp)$/i
    if (node.type === 'file' && imageExtensions.test(node.name)) return node
    if (node.children) {
      for (const child of node.children) {
        const found = findFirstImage(child)
        if (found) return found
      }
    }
    return null
  }

  function isLeafDirectory(node) {
    if (!node || node.type !== 'directory') return false
    if (!node.children || node.children.length === 0) return false
    return node.children.every(child => child.type === 'file')
  }

  function hasSubDirectories(node) {
    if (!node || node.type !== 'directory') return false
    if (!node.children || node.children.length === 0) return false
    return node.children.some(child => child.type === 'directory')
  }

  function getAllLeafDirectories(node, result = []) {
    if (!node || node.type !== 'directory') return result
    if (isLeafDirectory(node)) {
      const imageCount = node.children.filter(child =>
        child.type === 'file' && /\.(jpg|jpeg|png|tif|tiff|bmp|webp)$/i.test(child.name)
      ).length
      if (imageCount > 0) {
        result.push({ path: node.path, name: node.name, imageCount })
      }
    } else if (node.children) {
      for (const child of node.children) {
        if (child.type === 'directory') {
          getAllLeafDirectories(child, result)
        }
      }
    }
    return result
  }

  // ============================================================
  // 上传功能
  // ============================================================
  // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
  // 上传错误分类翻译（用户要求前后端日志必须记录清楚）：
  // 浏览器侧错误（文件读取失败/连接被拒等）后端物理上无法感知，只能由前端记录：
  // 此处翻译成明确原因，持久显示在弹窗标题（不再只靠3秒toast），并写入Console
  function classifyUploadError(err) {
    const msg = String(err?.message || '')
    if (msg.includes('ERR_FILE_NOT_FOUND')) {
      return '部分所选文件已无法读取（可能已被移动/重命名/删除、U盘网络盘断开、或路径超长）——请重新选择文件夹后再上传'
    }
    if (msg.includes('ERR_CONNECTION_REFUSED')) {
      return '无法连接服务（服务未启动或正在重启）——请确认服务已启动后重试'
    }
    if (msg.includes('timeout')) {
      return '上传超时（上限1小时）——建议分批上传'
    }
    if (err?.response?.data?.detail) {
      return String(err.response.data.detail)
    }
    return msg || '未知错误（详情见浏览器Console）'
  }

  async function uploadFiles(files, paths) {
    // 重置所有相关状态
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态修复
    // 新上传开始时清空批量完成摘要，生成面板回到初始"生成PDF"状态（避免上一轮批量完成态残留）
    batchGenerateSummary.value = null
    previewUrl.value = ''
    originalPreviewUrl.value = ''
    cleanedPreviewUrl.value = ''
    currentFilePath.value = ''
    selectedPath.value = ''
    siblingImages.value = []
    currentImageIndex.value = -1
    hasEdits.value = false
    canRestore.value = false
    isDrawing.value = false
    lastDrawPos.value = null
    clearHistory()
    scale.value = 1
    offsetX.value = 0
    offsetY.value = 0
    isDragging.value = false
    showRestoreConfirm.value = false
    showUnsavedWarning.value = false
    pendingAction.value = null
    pendingUploadFiles.value = null
    showReplaceConfirm.value = false
    pendingReplaceFiles.value = null
    showDownloadBtn.value = false

    // 重置步骤条到第一步
    currentStep.value = 1
    stepStatus.value = { 1: 'active', 2: 'pending', 4: 'pending' }
    manualActivePanel.value = 'clean'

    if (isBatchCleaning.value) {
      isBatchCleaning.value = false
      if (batchCleanTimer.value) {
        clearInterval(batchCleanTimer.value)
        batchCleanTimer.value = null
      }
      if (batchCleanElapsedTimer.value) {
        clearInterval(batchCleanElapsedTimer.value)
        batchCleanElapsedTimer.value = null
      }
    }
    showBatchCleanProgress.value = false
    batchCleanElapsed.value = 0
    batchCleanStatus.value = {
      status: 'idle', progress: 0, current_file: '', current_path: '', message: '', images_cleaned: false
    }

    if (isBatchRedrawing.value) {
      isBatchRedrawing.value = false
      if (batchRedrawTimer.value) {
        clearInterval(batchRedrawTimer.value)
        batchRedrawTimer.value = null
      }
      if (batchRedrawElapsedTimer.value) {
        clearInterval(batchRedrawElapsedTimer.value)
        batchRedrawElapsedTimer.value = null
      }
    }
    showBatchRedrawProgress.value = false
    batchRedrawElapsed.value = 0
    batchRedrawStatus.value = { status: 'idle', progress: 0, current_file: '', message: '' }

    fileTree.value = { name: '', type: 'directory', children: [] }
    expandedPaths.value = new Set()
    currentTask.value = null

    isUploading.value = true

    // xuechong 2026-06-03 显示上传弹窗（使用实际文件信息，不依赖 currentTask）
    const folderDisplayName = files.length > 0
      ? (paths[0] || files[0].webkitRelativePath || files[0].name).split('/')[0] || '未命名文件夹'
      : '未命名文件夹'
    showUploadModal.value = true
    uploadModalTitle.value = '文件上传'
    uploadModalPhase.value = 'preparing'
    uploadModalCurrentFile.value = ''
    // 上传弹窗期间使用临时变量（currentTask 尚未设置）
    uploadModalFolderName.value = folderDisplayName
    uploadModalTotalFiles.value = files.length
    uploadProgress.value = { visible: false, current: 0, total: files.length, percent: 0, uploading: false, message: '' }
    _startUploadTimer()

    try {
      // xuechong 2026-06-01 创建 AbortController 以支持取消上传
      abortController.value = new AbortController()

      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 上传前逐文件可读性预检（全量流式读取版）：只读头1KB不够（现场实测：预检全过、XHR全量读仍失败），
      // 改为流式读完整个文件（不整体载入内存），文件中段损坏/占位盘/被锁/上传前被移动全部能提前暴露；
      // 无论结果如何都输出一行预检标记日志，部署是否生效一眼可辨
      uploadModalTitle.value = `正在检查文件可读性 (0/${files.length})`
      const unreadable = []
      for (let i = 0; i < files.length; i++) {
        if (i % 20 === 0) {
          uploadModalTitle.value = `正在检查文件可读性 (${i}/${files.length})`
        }
        try {
          const reader = files[i].stream().getReader()
          while (true) {
            const { done } = await reader.read()
            if (done) break
          }
        } catch (e) {
          unreadable.push({ path: paths[i] || files[i].webkitRelativePath || files[i].name, error: e?.name || String(e) })
        }
      }
      console.log(`[上传预检] 完成：共 ${files.length} 个文件，无法读取 ${unreadable.length} 个（此行存在即代表新版预检已生效）`)
      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 用户决策：整体成败语义——任何一个文件读不了，整个上传就失败，
      // 绝不部分上传（档案系统缺一页=缺一文件，用户拿着不完整列表继续操作不可接受）
      if (unreadable.length > 0) {
        console.error('[上传预检] 以下文件浏览器无法读取，本次上传整体中止（未上传任何文件）：',
          JSON.parse(JSON.stringify(unreadable)))
        _stopUploadTimer()
        uploadModalPhase.value = 'failed'
        const detail = unreadable.map(u => u.path).slice(0, 5).join('；')
          + (unreadable.length > 5 ? ` ……等共 ${unreadable.length} 个` : '')
        uploadModalTitle.value = `上传失败：${unreadable.length} 个文件无法读取，已整体中止`
        showToast('上传失败（整体中止）：无法读取的文件：' + detail, 'error')
        return
      }

      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 分批上传+失败自动二分定位（一次性根治）：旧实现3555个文件挤一个HTTP请求，
      // 任何一个文件读不了整个请求就 net::ERR_FILE_NOT_FOUND 全军覆没且无法定位。
      // 现改为每批100个分批传：某批失败自动对半二分递归重试，
      // 单个文件失败即元凶点名跳过，其余全部传完；坏文件路径记录 Console/弹窗并上报后端日志
      uploadModalPhase.value = 'uploading'
      const CHUNK = 100
      let taskId = null
      let uploadedCount = 0
      const failedFiles = []

      const sendBatch = async (segFiles, segPaths) => {
        const fd = new FormData()
        for (let i = 0; i < segFiles.length; i++) {
          fd.append('files', segFiles[i], segFiles[i].name)
          fd.append('paths', segPaths[i] || segFiles[i].webkitRelativePath || segFiles[i].name)
        }
        return api.uploadFolder(fd, (event) => {
          if (event.total) {
            const netPct = Math.round((event.loaded / event.total) * 100)
            const segIdx = Math.min(Math.floor(netPct / 100 * segFiles.length), segFiles.length - 1)
            uploadModalCurrentFile.value = segFiles[segIdx]?.name || ''
            const done = uploadedCount + netPct / 100 * segFiles.length
            uploadProgress.value = { visible: false, current: Math.round(done), total: files.length,
              percent: Math.round(done / files.length * 100), uploading: true, message: '' }
          }
        }, abortController.value.signal, taskId)
      }

      // 二分重试：批失败对半拆分递归；单文件失败=元凶，点名跳过；好文件继续传完
      const sendWithBisect = async (segFiles, segPaths) => {
        if (abortController.value?.signal?.aborted) {
          throw Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' })
        }
        try {
          const r = await sendBatch(segFiles, segPaths)
          taskId = r.data.task_id
          uploadedCount += segFiles.length
          return
        } catch (err) {
          if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') throw err
          if (segFiles.length === 1) {
            const badPath = segPaths[0] || segFiles[0].webkitRelativePath || segFiles[0].name
            // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
            // 失败记录增强：补充 HTTP 状态码/axios错误码/后端detail，
            // 用于定位 401 死循环等全局性拒绝（此前只记路径，现场无法判断原因）
            failedFiles.push({
              path: badPath,
              error: err?.message || String(err),
              status: err?.response?.status || 0,
              code: err?.code || '',
              detail: String(err?.response?.data?.detail || '').slice(0, 200)
            })
            console.error('[上传定位] 该文件上传失败，已跳过：', badPath, err)
            return
          }
          console.warn(`[上传分批] 本批 ${segFiles.length} 个失败，自动二分定位中：`, err?.message)
          const mid = Math.ceil(segFiles.length / 2)
          await sendWithBisect(segFiles.slice(0, mid), segPaths.slice(0, mid), false)
          await sendWithBisect(segFiles.slice(mid), segPaths.slice(mid), false)
        }
      }

      const totalBatches = Math.ceil(files.length / CHUNK)
      for (let i = 0; i < files.length; i += CHUNK) {
        uploadModalTitle.value = `正在上传 ${folderDisplayName}（第 ${Math.floor(i / CHUNK) + 1}/${totalBatches} 批）`
        await sendWithBisect(files.slice(i, i + CHUNK), paths.slice(i, i + CHUNK))
      }

      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 用户决策：整体成败语义——二分定位出任何失败文件，整个上传判失败，
      // 并删除服务端已部分上传的任务，绝不留不完整列表让用户继续后续操作
      if (failedFiles.length > 0) {
        if (taskId) {
          try {
            await api.deleteUploadTask(taskId)
            console.warn(`[上传] 已删除服务端不完整任务 ${taskId}（防止用户在不完整列表上继续操作）`)
          } catch (delErr) {
            console.error('[上传] 删除不完整任务失败，请手动删除任务：', taskId, delErr)
          }
        }
        // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        // toast 明细带 HTTP 状态码（如 a005.tif(HTTP 401)），现场一眼区分鉴权/服务端/网络错误
        const detail = failedFiles.slice(0, 5).map(f => f.path + (f.status ? `(HTTP ${f.status})` : '')).join('；')
          + (failedFiles.length > 5 ? ` ……等共 ${failedFiles.length} 个` : '')
        // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        // 组装诊断包上报后端运行日志（免鉴权端点 /api/upload-diagnostic，fire-and-forget 不产生新报错）：
        // 401 场景下服务端业务日志原本零痕迹，此处补齐前端侧证据（状态码/构建版本/页面运行时长）
        let _authSaved = {}
        try { _authSaved = JSON.parse(localStorage.getItem('ds_auth') || '{}') } catch (e) { /* 忽略 */ }
        const _diagPayload = {
          event: 'upload_abort',
          folder: folderDisplayName,
          total: files.length,
          uploaded: uploadedCount,
          task_id: taskId || '',
          failed: failedFiles,
          build: (typeof __APP_BUILD_INFO__ !== 'undefined') ? __APP_BUILD_INFO__ : null,
          page_uptime_sec: Math.round(performance.now() / 1000),
          // xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
          // 用户名取值键名纠正：本地存储结构里用户信息存在 user 键下，原来误读 userInfo 键，
          // 导致诊断包里"用户="永远为空，排查时分不清是哪个用户碰到的
          user: _authSaved?.user?.username || '',
          user_agent: navigator.userAgent
        }
        console.error(`[上传失败] ${failedFiles.length} 个文件上传失败，整体已中止（诊断包如下）：`, _diagPayload)
        api.reportUploadDiagnostic(_diagPayload)
        _stopUploadTimer()
        uploadModalPhase.value = 'failed'
        uploadModalTitle.value = `上传失败：${failedFiles.length} 个文件上传失败，已整体中止`
        showToast('上传失败（整体中止，不完整任务已删除）：失败文件：' + detail, 'error')
        return
      }
      if (!taskId) {
        throw new Error('全部批次上传失败（原因见浏览器Console）')
      }

      uploadModalPhase.value = 'processing'
      uploadModalTitle.value = '服务器处理中...'

      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 分批上传后由前端汇总任务信息（res 单批响应已不存在）
      currentTask.value = {
        task_id: taskId,
        folder_name: folderDisplayName,
        status: 'uploaded',
        total_files: uploadedCount,
        progress: 0,
        message: '已上传 ' + uploadedCount + ' 个文件，等待处理',
        can_download: false
      }

      // xuechong 2026-06-01 持久化 taskId 到 sessionStorage
      saveTaskIdToStorage(taskId)

      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 上传已成功的后续处理单独捕获：后端已返回200时，
      // 加载文件树等JS环节出错不再误报"上传失败"，避免误导排查方向
      try {
        await loadFileTree(taskId)
        // 自动选中根目录，确保后续自动模式能获取到目录路径
        if (fileTree.value) {
          selectedPath.value = fileTree.value.path
        }
      } catch (postErr) {
        console.error('[上传] 后端已成功，加载文件列表出错:', postErr)
        showToast('已上传完成，但加载文件列表出错：' + (postErr?.message || postErr), 'warning')
      }

      // xuechong 2026-06-02 上传成功，弹窗显示完成状态（不自动关闭，用户手动关闭）
      _stopUploadTimer()
      uploadModalPhase.value = 'completed'
      uploadModalTitle.value = '上传完成'
      showToast(`已上传 ${uploadedCount} 个文件`, 'success')
      advanceStep()
    } catch (err) {
      _stopUploadTimer()
      // xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 完整错误对象写入Console（F12永久可见）+ 弹窗持久显示分类原因
      console.error('[上传] 失败完整错误:', err)
      // xuechong 2026-06-01 区分用户取消和真正的上传错误
      if (err && (err.code === 'ERR_CANCELED' || err.name === 'CanceledError' || err.message === 'canceled')) {
        uploadModalPhase.value = 'cancelled'
        uploadModalTitle.value = '上传已取消'
        showToast('上传已取消', 'info')
      } else {
        uploadModalPhase.value = 'failed'
        const reason = classifyUploadError(err)
        uploadModalTitle.value = '上传失败：' + reason
        showToast('上传失败: ' + reason, 'error')
      }
    } finally {
      isUploading.value = false
      abortController.value = null  // xuechong 2026-06-01 清理 AbortController
    }
  }

  // xuechong 2026-06-01 将当前 taskId 持久化到 sessionStorage
  function saveTaskIdToStorage(taskId) {
    try { sessionStorage.setItem('ds_current_task_id', taskId) } catch (e) { /* 忽略 */ }
  }
  function loadTaskIdFromStorage() {
    try { return sessionStorage.getItem('ds_current_task_id') } catch (e) { return null }
  }
  function clearTaskIdFromStorage() {
    try { sessionStorage.removeItem('ds_current_task_id') } catch (e) { /* 忽略 */ }
  }

  // xuechong 2026-06-01 检查服务器上是否有活跃任务，用于页面恢复
  // xuechong 2026-06-02 获取所有活跃任务列表（多任务恢复支持）
  const activeTaskList = ref([])

  // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
  // 未完成任务（含中断）：弹框数据源，按创建时间倒序；进入模块页不再自动恢复，由用户主动选择
  const unfinishedTaskList = ref([])
  const unfinishedCount = computed(() => unfinishedTaskList.value.length)

  // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 嵌入会话数据过滤（用户口径：嵌入式不存在历史数据）：嵌入页只显示"本页签会话期间"产生的
  // 任务与记录——会话起始时刻由 router 在首次带embed进入时写入 sessionStorage；非嵌入返回0不过滤
  function p_embedSessionStartAt() {
    try {
      if (sessionStorage.getItem('ds_embed_mode') !== '1') return 0
      const ts = Number(sessionStorage.getItem('ds_embed_session_at') || 0)
      return ts > 0 ? ts : 0
    } catch (e) {
      return 0
    }
  }

  // 记录时间解析：兼容任务ISO格式（2026-09-28T00:34:32）与历史记录格式（2026-09-29 11:54:36），
  // 解析失败返回0（视为会话内，宁可多显示不误隐藏本轮数据）
  function p_parseRecordTime(timeStr) {
    try {
      const normalized = String(timeStr || '').replace(' ', 'T')
      const ms = new Date(normalized).getTime()
      return isNaN(ms) ? 0 : ms
    } catch (e) {
      return 0
    }
  }

  function p_inEmbedSession(timeStr) {
    const startAt = p_embedSessionStartAt()
    if (startAt <= 0) return true
    const createdMs = p_parseRecordTime(timeStr)
    if (createdMs <= 0) return true
    return createdMs >= startAt
  }

  // xuechong 2026-09-30 研发需求-0164 任务在嵌入页的可见性：演示链任务（form-in八步页经代理上传，
  // 任务带source=form-in标记）恒可见，其余按会话时间过滤——既保证"八步页先上传、嵌入页后打开"
  // 能立刻看到刚传的任务，又维持"嵌入式不存在历史数据"（直连使用与历史测试产生的任务仍被滤掉）
  function p_taskInEmbedView(task) {
    if (task && task.source === 'form-in') { return true }
    return p_inEmbedSession(task && task.created_at)
  }

  // xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 转换/上传记录在嵌入页的可见性：与任务同款豁免——演示链记录（source=form-in，随所属任务
  // 打同标记；2026-10-06 前的旧记录由服务端读取列表时按 task_id 回查补齐）恒可见，其余按会话
  // 时间过滤（"嵌入式不存在历史数据"口径不变）。修复：八步页先上传、嵌入页后打开时任务列表
  // 有数据但"转换记录"弹框被会话起点滤成空列表的问题
  function p_recordInEmbedView(item) {
    if (item && item.source === 'form-in') { return true }
    return p_inEmbedSession(item && item.created_at)
  }

  async function fetchUnfinishedTasks() {
    try {
      const res = await api.getActiveTasks()
      const all = res.data.active_tasks || []
      unfinishedTaskList.value = all
        .filter(t => !['completed', 'failed', 'cancelled'].includes(t.status))
        // xuechong 2026-09-30 嵌入会话过滤：会话开始前的历史任务不在嵌入页显示（徽标计数同源）；
        // 演示链任务（source=form-in）恒可见（八步页先上传、嵌入页后打开也能立刻看到）
        .filter(t => p_taskInEmbedView(t))
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    } catch (err) {
      devLog('error', '[未完成任务] 获取失败:', err)
    }
  }

  async function checkServerActiveTask() {
    try {
      const res = await api.getActiveTasks()
      const allTasks = res.data.active_tasks || []
      // V3.1.01 xuechong 2026-07-25 activeTaskList 只保留真正活跃的任务（排除已完成/失败/取消/中断）
      activeTaskList.value = allTasks.filter(
        t => !['completed', 'failed', 'cancelled', 'interrupted'].includes(t.status)
      )

      // xuechong 2026-09-30 研发需求-0164 嵌入会话过滤：checkServerActiveTask 在嵌入模式下只认
      // 会话期间创建的任务与演示链任务（source=form-in），历史任务不得带进工作区
      const sessionTasks = p_embedSessionStartAt() > 0
        ? allTasks.filter(t => p_taskInEmbedView(t))
        : allTasks

      // V3.1.01 xuechong 2026-07-25 优先恢复 sessionStorage 中指定的任务（支持从首页“继续处理”带 task_id 跳转）
      const savedTaskId = loadTaskIdFromStorage()
      if (savedTaskId && sessionTasks.length > 0) {
        const matched = sessionTasks.find(t => t.task_id === savedTaskId)
        if (matched) return matched
      }

      // 从所有任务中找最新的（包括已完成的，以便用户继续下载）
      if (sessionTasks.length > 0) {
        sessionTasks.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
        return sessionTasks[0]
      }
      // 服务器无任务，尝试从 sessionStorage 恢复
      if (savedTaskId) {
        try {
          const taskRes = await api.getUploadTask(savedTaskId)
          if (taskRes.data && taskRes.data.task_id) {
            // xuechong 2026-09-30 嵌入会话过滤：按id兜底恢复同样不得带出会话前的历史任务
            if (!p_taskInEmbedView(taskRes.data)) {
              return null
            }
            return taskRes.data
          }
        } catch {
          clearTaskIdFromStorage()
        }
      }
      return null
    } catch (err) {
      devLog('error', '[checkServerActiveTask] 检查失败:', err)
      return null
    }
  }

  // xuechong 2026-06-01 从服务器恢复任务状态（包括文件树、轮询等）
  async function restoreTaskState(activeTask) {
    if (!activeTask || !activeTask.task_id) return false

    currentTask.value = {
      task_id: activeTask.task_id,
      folder_name: activeTask.folder_name,
      status: activeTask.status || 'unknown',
      total_files: activeTask.total_files || 0,
      progress: activeTask.progress || 0,
      message: activeTask.message || '',
      can_download: activeTask.can_download || false
    }

    // 保存 taskId 到 sessionStorage
    saveTaskIdToStorage(activeTask.task_id)

    // 加载文件树
    try {
      await loadFileTree(activeTask.task_id)
    } catch (err) {
      devLog('error', '[restoreTaskState] 加载文件树失败:', err)
    }

    // 根据任务状态恢复步骤和轮询
    const taskStatus = activeTask.status
    if (taskStatus === 'uploaded') {
      // 已上传但未处理，停在步骤1，手动模式切换到修图面板方便用户直接操作
      currentStep.value = 1
      stepStatus.value = { 1: 'active', 2: 'pending', 4: 'pending' }
      if (operationMode.value === 'manual') {
        manualActivePanel.value = 'clean'
      }
      showToast('已恢复上传任务，请继续处理', 'info')
    } else if (taskStatus === 'processing') {
      // 正在处理中，显示处理进度并恢复轮询
      currentStep.value = 2
      stepStatus.value = { 1: 'completed', 2: 'active', 4: 'pending' }
      if (operationMode.value === 'manual') {
        manualActivePanel.value = 'clean'
      }
      startPolling()
      showToast('任务处理中，已恢复进度跟踪', 'info')
    } else if (taskStatus === 'interrupted') {
      // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // 中断任务恢复分支：回到步骤2继续修图
      // （后端断点清单保证重跑时已完成文件不重复处理）
      currentStep.value = 2
      stepStatus.value = { 1: 'completed', 2: 'active', 4: 'pending' }
      if (operationMode.value === 'manual') {
        manualActivePanel.value = 'clean'
      }
      showToast('任务已中断，可继续修图（已完成部分不会重复处理）', 'warning')
    } else if (taskStatus === 'completed') {
      // 已完成，显示下载按钮
      currentStep.value = 4
      stepStatus.value = { 1: 'completed', 2: 'completed', 4: 'active' }
      if (operationMode.value === 'manual') {
        manualActivePanel.value = 'generate'
      }
      showDownloadBtn.value = true
      showToast('上次处理已完成，可直接下载', 'info')
    } else if (taskStatus === 'failed' || taskStatus === 'cancelled') {
      // 失败或取消，停在步骤1让用户重新处理
      currentStep.value = 1
      stepStatus.value = { 1: 'active', 2: 'pending', 4: 'pending' }
      if (operationMode.value === 'manual') {
        manualActivePanel.value = 'clean'
      }
      showToast('上次任务' + (taskStatus === 'cancelled' ? '已取消' : '处理失败') + '，可重新上传', 'warning')
    }

    // 自动选中根目录，确保后续批量操作有目标路径
    if (fileTree.value && fileTree.value.path) {
      selectedPath.value = fileTree.value.path
    }

    // 如果正在修图，恢复修图状态
    if (activeTask.clean_status === 'processing') {
      isBatchCleaning.value = true
      showBatchCleanProgress.value = true
      batchCleanStatus.value = {
        status: 'processing',
        progress: activeTask.clean_progress || 0,
        current_file: activeTask.clean_current_file || '',
        message: activeTask.clean_message || '正在修图...'
      }
      // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
      // 嵌入模式下由智能收集整理页（form-in）驱动的任务，本页恢复修图进度只做展示，
      // 修图完成后不自动生成PDF——八步页同样会链式触发生成，双页同时驱动会重复处理，
      // 且第二次处理重写PDF的窗口内form-in下载会拿到半成品被PDF合法性校验拒绝；
      // 直连模式恢复与非form-in来源任务保持原断点续跑自动生成行为不变
      let resumeOnly = false
      try {
        if (sessionStorage.getItem('ds_embed_mode') === '1' && (activeTask.source || '') === 'form-in') {
          resumeOnly = true
        }
      } catch (e) { resumeOnly = false }
      startBatchCleanPolling(resumeOnly)
    }

    return true
  }

  // xuechong 2026-06-01 取消上传（中止HTTP请求 + 通知后端取消任务）
  async function cancelUpload() {
    _stopUploadTimer()
    // 中止正在进行的上传请求
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    // 通知后端取消任务（如果任务已创建）
    if (currentTask.value && currentTask.value.task_id) {
      try {
        await api.cancelTask(currentTask.value.task_id)
      } catch (err) {
        devLog('error', '[取消上传] 后端取消失败:', err)
      }
    }
    // 重置上传状态
    isUploading.value = false
    uploadModalPhase.value = 'cancelled'
    uploadModalTitle.value = '上传已取消'
    showToast('上传已取消', 'info')
  }

  // xuechong 2026-06-01 关闭上传弹窗（用户手动点击完成/关闭按钮）
  function closeUploadModal() {
    showUploadModal.value = false
    _stopUploadTimer()
  }

  // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 前端非图片文件过滤（方案A）
  // 白名单与 backend\services\image_utils.py 的 SUPPORTED_EXTENSIONS 严格一致（七种，后端为唯一权威，
  // 若后端调整此处必须同步）；大小写不敏感（后端 suffix.lower() 同款语义）
  const IMAGE_UPLOAD_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp']

  function isSupportedImageFile(file) {
    const name = file?.name || ''
    const dot = name.lastIndexOf('.')
    if (dot < 0) return false
    return IMAGE_UPLOAD_EXTENSIONS.includes(name.slice(dot).toLowerCase())
  }

  // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 上传路径取值：散图直传时handleImageUpload给文件挂__uploadPath（图片时间戳文件夹/文件名），
  // 文件夹上传时走webkitRelativePath，两者都没有回落到文件名（平铺到任务根目录）
  function uploadPathOf(file) {
    return file.__uploadPath || file.webkitRelativePath || file.name
  }

  // 散图直传：给每个图片文件补逻辑路径（自动归入按时间命名的文件夹，维持"一文件夹一PDF"口径），
  // 守卫（非图片过滤/忙/未保存编辑/替换确认）与后续流程全部复用文件夹上传handleFolderUpload
  function handleImageUpload(event) {
    const allFiles = Array.from(event.target.files || [])
    const now = new Date()
    const pad2 = (num) => String(num).padStart(2, '0')
    const folderName = `图片${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}-${pad2(now.getHours())}${pad2(now.getMinutes())}${pad2(now.getSeconds())}`
    for (const file of allFiles) {
      file.__uploadPath = folderName + '/' + file.name
    }
    return handleFolderUpload(event)
  }

  async function handleFolderUpload(event) {
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 前端非图片文件过滤（方案A）
    // 源头过滤：归档文件夹常混有 PDF/DOCX 等非图片文件，它们注定被后端丢弃，却可能死在前端
    // 可读性预检上按"整体中止"规则炸掉全部图片上传（还白占流量与服务器磁盘）。
    // 故在进入预检/上传队列前按七种图片扩展名白名单过滤；"整体中止"保护语义保留给真图片文件
    const allFiles = Array.from(event.target.files || [])
    if (!allFiles || allFiles.length === 0) return
    const files = []
    let ignoredCount = 0
    const ignoredExts = new Set()
    for (const f of allFiles) {
      if (isSupportedImageFile(f)) {
        files.push(f)
      } else {
        ignoredCount++
        const name = f.name || ''
        const dot = name.lastIndexOf('.')
        ignoredExts.add(dot >= 0 ? name.slice(dot).toLowerCase() : '无扩展名')
      }
    }
    if (ignoredCount > 0) {
      // 持久提示（error 类不自动消失，点击关闭）：用户必须能感知少了文件
      showToast(`已忽略 ${ignoredCount} 个非图片文件（${Array.from(ignoredExts).join('、')}），仅上传图片格式（PNG/JPG/JPEG/BMP/TIF/TIFF/WEBP）`, 'error')
    }
    if (files.length === 0) {
      showToast('所选文件夹中没有支持的图片文件（支持：PNG/JPG/JPEG/BMP/TIF/TIFF/WEBP）', 'error')
      event.target.value = ''
      return
    }
    if (isBusy.value) {
      showToast('正在处理中，请稍候', 'warning')
      event.target.value = ''
      return
    }

    if (hasEdits.value) {
      pendingUploadFiles.value = files
      pendingAction.value = async () => {
        const f = pendingUploadFiles.value
        pendingUploadFiles.value = null
        if (f) {
          const paths = f.map(file => uploadPathOf(file))
          await uploadFiles(f, paths)
        }
      }
      showUnsavedWarning.value = true
      event.target.value = ''
      return
    }

    // 已有上传任务时，弹出替换确认，防止静默覆盖
    if (currentTask.value) {
      pendingReplaceFiles.value = files
      showReplaceConfirm.value = true
      event.target.value = ''
      return
    }

    const paths = files.map(file => uploadPathOf(file))
    await uploadFiles(files, paths)
    event.target.value = ''
  }

  async function confirmReplace() {
    const files = pendingReplaceFiles.value
    pendingReplaceFiles.value = null
    showReplaceConfirm.value = false
    if (files) {
      const paths = files.map(file => uploadPathOf(file))
      await uploadFiles(files, paths)
    }
  }

  function cancelReplace() {
    pendingReplaceFiles.value = null
    showReplaceConfirm.value = false
  }

  async function loadFileTree(taskId) {
    if (!taskId) { devLog('error', '[文件树] taskId为空'); return }
    try {
      const res = await api.getUploadFileTree(taskId)
      console.log('[文件树] API响应:', JSON.stringify(res.data))
      if (res.data && res.data.tree) {
        fileTree.value = res.data.tree
        console.log('[文件树] 已设置, children数量:', fileTree.value.children?.length || 0)
        if (!fileTree.value.children || fileTree.value.children.length === 0) {
          showErrorModal('文件树为空', '上传成功但文件列表为空(children=0)，请重启服务后重试')
        }
      } else {
        console.error('[文件树] 返回数据异常:', res.data)
        showErrorModal('文件树为空', '服务器返回的文件列表为空')
      }
    } catch (err) {
      console.error('[文件树] 加载失败:', err)
      showErrorModal('文件树加载失败', err?.response?.data?.detail || err.message || '未知错误')
    }
  }

  // ============================================================
  // 文件选择
  // ============================================================
  async function handleSelect(node) {
    selectedPath.value = node.path

    if (node.type === 'file' && currentTask.value) {
      resetEditState()
      currentFilePath.value = node.path
      updateSiblingImages(node.path)

      let hasBackup = false
      try {
        const res = await api.checkBackup(currentTask.value.task_id, node.path)
        hasBackup = res.data.has_backup
        canRestore.value = hasBackup
      } catch (err) {
        canRestore.value = false
      }

      if (hasBackup) {
        originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, node.path)
      } else {
        originalPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, node.path)
      }
      previewUrl.value = originalPreviewUrl.value
      cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, node.path)
      isLoadingCleaned.value = false
    } else {
      // 目录: 递归查找第一个图片文件并预览
      // 注意：仅加载预览，不改变 selectedPath（否则批处理目标会被意外改变）
      const firstImage = findFirstImage(node)
      if (firstImage) {
        currentFilePath.value = firstImage.path
        updateSiblingImages(firstImage.path)
        const timestamp = Date.now()
        originalPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, firstImage.path)
        previewUrl.value = originalPreviewUrl.value
        cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, firstImage.path)
        isLoadingCleaned.value = false
        hasEdits.value = false
        canRestore.value = false
        return
      }
      previewUrl.value = ''
      originalPreviewUrl.value = ''
      cleanedPreviewUrl.value = ''
      currentFilePath.value = ''
    }
  }

  // ============================================================
  // 文件/文件夹删除
  // ============================================================
  function handleDelete() {
    if (!selectedPath.value) return  // 根目录（path=''）不可删除
    showDeleteConfirm.value = true
  }

  async function confirmDelete() {
    if (!currentTask.value || !selectedPath.value) return
    try {
      const res = await api.deleteUploadFile(currentTask.value.task_id, selectedPath.value)
      // 更新剩余文件数
      if (res.data.total_files !== undefined) {
        currentTask.value.total_files = res.data.total_files
      }
      // 清除选中状态
      selectedPath.value = ''
      previewUrl.value = ''
      originalPreviewUrl.value = ''
      cleanedPreviewUrl.value = ''
      currentFilePath.value = ''
      // 刷新文件树
      await loadFileTree(currentTask.value.task_id)
      showToast('删除成功', 'success')
    } catch (err) {
      devLog('error', '[删除文件] 失败:', err)
      showToast(err.response?.data?.detail || '删除失败', 'error')
    } finally {
      showDeleteConfirm.value = false
    }
  }

  function resetEditState() {
    scale.value = 1
    offsetX.value = 0
    offsetY.value = 0
    hasEdits.value = false
    isDrawing.value = false
    isDragging.value = false
    canvasCtx = null
    imageDrawnOnCanvas = false
    lastDrawPos.value = null
    clearHistory()
  }

  // ============================================================
  // 图片加载事件
  // ============================================================
  function onImageLoad() {}

  function onCleanedImageLoad() {
    isLoadingCleaned.value = false
    nextTick(() => {
      initEditCanvas()
    })
  }

  // 获取修图区的 canvas 和 img 元素（直接查 DOM，不依赖 Vue ref 连接）
  function getCanvasElements() {
    const canvas = document.querySelector('.edited-panel canvas.edit-canvas')
    const img = document.querySelector('.edited-panel img.preview-image')
    return { canvas, img }
  }

  async function initEditCanvas() {
    const { canvas, img } = getCanvasElements()
    if (!canvas || !img) return
    if (!img.naturalWidth || !img.naturalHeight) return

    // 内部像素尺寸 = 图片原始分辨率
    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight

    // CSS 显示尺寸 = 与图片 object-fit:contain 显示尺寸一致
    // 避免因宽高比不同导致 canvas 与图片错位
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

  // ============================================================
  // 目录展开/收起
  // ============================================================
  function handleToggle(path) {
    const next = new Set(expandedPaths.value)
    if (next.has(path)) {
      next.delete(path)
    } else {
      next.add(path)
    }
    expandedPaths.value = next
  }

  function expandAll() {
    function expand(node) {
      if (node.type === 'directory') {
        expandedPaths.value.add(node.path)
        node.children?.forEach(expand)
      }
    }
    expand(fileTree.value)
  }

  function collapseAll() {
    expandedPaths.value.clear()
  }

  // ============================================================
  // 图片缩放和拖拽
  // ============================================================
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
    document.addEventListener('mousemove', onDrag)
    document.addEventListener('mouseup', stopDrag)
  }

  function onDrag(e) {
    if (!isDragging.value) return
    offsetX.value = e.clientX - dragStart.value.x
    offsetY.value = e.clientY - dragStart.value.y
  }

  function stopDrag() {
    isDragging.value = false
    document.removeEventListener('mousemove', onDrag)
    document.removeEventListener('mouseup', stopDrag)
  }

  // ============================================================
  // 手动修图绘制
  // ============================================================
  async function startDraw(e) {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：画布只读（涂画属修改类，与工具栏同口径）
    if (isBusy.value) return
    if (!canvasCtx) await initEditCanvas()
    if (!canvasCtx) {
      devLog('warn', '[DRAW] canvasCtx still null')
      return
    }

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

  // ============================================================
  // 撤销/重做
  // ============================================================
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
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：与工具栏 isBusy 口径一致（纯本地状态，静默拦截）
    if (isBusy.value) return
    if (!canUndo.value || !canvasCtx) return
    historyIndex.value--
    const imageData = editHistory.value[historyIndex.value]
    canvasCtx.putImageData(imageData, 0, 0)
    if (historyIndex.value === 0) hasEdits.value = false
  }

  function redoEdit() {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：与工具栏 isBusy 口径一致（纯本地状态，静默拦截）
    if (isBusy.value) return
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

  // ============================================================
  // 图片切换（上一张/下一张）
  // ============================================================
  function updateSiblingImages(filePath) {
    const lastSlash = filePath.lastIndexOf('/')
    const parentPath = lastSlash > 0 ? filePath.substring(0, lastSlash) : ''
    const parentNode = parentPath ? findNodeByPath(fileTree.value, parentPath) : fileTree.value

    if (!parentNode || !parentNode.children) {
      siblingImages.value = []
      currentImageIndex.value = -1
      return
    }

    const imageExtensions = /\.(jpg|jpeg|png|tif|tiff|bmp|webp)$/i
    const images = parentNode.children
      .filter(child => child.type === 'file' && imageExtensions.test(child.name))
      .map(child => child.path)

    siblingImages.value = images
    currentImageIndex.value = images.indexOf(filePath)
  }

  async function goPrevImage() {
    if (!canGoPrev.value) return
    if (hasEdits.value) {
      pendingAction.value = () => doGoPrevImage()
      showUnsavedWarning.value = true
      return
    }
    await doGoPrevImage()
  }

  async function doGoPrevImage() {
    const prevPath = siblingImages.value[currentImageIndex.value - 1]
    const prevNode = findNodeByPath(fileTree.value, prevPath)
    if (prevNode) await handleSelect(prevNode)
  }

  async function goNextImage() {
    if (!canGoNext.value) return
    if (hasEdits.value) {
      pendingAction.value = () => doGoNextImage()
      showUnsavedWarning.value = true
      return
    }
    await doGoNextImage()
  }

  async function doGoNextImage() {
    const nextPath = siblingImages.value[currentImageIndex.value + 1]
    const nextNode = findNodeByPath(fileTree.value, nextPath)
    if (nextNode) await handleSelect(nextNode)
  }

  // ============================================================
  // 未保存修改处理
  // ============================================================
  async function saveAndContinue() {
    showUnsavedWarning.value = false
    await saveManualEdit()
    if (hasEdits.value) return  // 保存失败，放弃后续操作
    if (pendingAction.value) {
      await pendingAction.value()
      pendingAction.value = null
    }
  }

  async function discardAndContinue() {
    showUnsavedWarning.value = false
    hasEdits.value = false
    if (pendingAction.value) {
      await pendingAction.value()
      pendingAction.value = null
    }
  }

  function cancelPendingAction() {
    showUnsavedWarning.value = false
    pendingAction.value = null
  }

  function handleBatchClean() {
    if (hasEdits.value) {
      pendingAction.value = () => startBatchClean()
      showUnsavedWarning.value = true
      return
    }
    startBatchClean()
  }

  // 诊断函数：检查为什么批量修图按钮不可用
  function diagnoseBatchClean() {
    if (!currentTask.value) return '无活跃任务'
    if (isUploading.value) return '正在上传中'
    if (isProcessing.value) return '正在处理PDF中'
    if (isBatchCleaning.value) return '正在修图中'
    if (isBatchPdfProcessing.value) return '正在批量生成PDF'
    if (isBatchRedrawing.value) return '正在批量重绘'
    if (!selectedPath.value) return '未选择路径'
    const node = effectiveDirectoryNode.value
    if (!node) return '未找到目录节点'
    if (node.type !== 'directory') return '选择的是文件，不是目录'
    if (!isLeafDirectory(node) && !hasSubDirectories(node)) return '目录为空'
    return null // 全部通过
  }

  function handleRestoreImage() {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：生成PDF/修图/批量中还原会改动正被处理的文件
    if (isBusy.value) {
      showToast('正在处理中，请等待完成后再操作', 'warning')
      return
    }
    if (hasEdits.value) {
      pendingAction.value = () => confirmRestoreImage()
      showUnsavedWarning.value = true
      return
    }
    confirmRestoreImage()
  }

  function handleStartProcess() {
    if (hasEdits.value) {
      pendingAction.value = () => startProcess()
      showUnsavedWarning.value = true
      return
    }
    startProcess()
  }

  // ============================================================
  // 旋转图片
  // ============================================================
  async function rotateCurrentImage(direction) {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：修图会整目录重写图片、生成PDF期间
    // 图片正被打进PDF，此时旋转同一批文件必然互相踩（isBusy=上传/处理/修图/批量全口径）
    if (isBusy.value) {
      showToast('正在处理中，请等待完成后再操作', 'warning')
      return
    }
    if (!currentTask.value || !currentFilePath.value) {
      showToast('请先选择图片', 'warning')
      return
    }
    if (isRotating.value) return

    // 检查未保存的修改
    if (hasEdits.value) {
      pendingAction.value = () => doRotateCurrentImage(direction)
      showUnsavedWarning.value = true
      return
    }

    await doRotateCurrentImage(direction)
  }

  async function doRotateCurrentImage(direction) {
    if (isRotating.value) return

    isRotating.value = true
    const directionText = direction === 'left' ? '左旋转' : '右旋转'

    try {
      const res = await api.rotateImage(currentTask.value.task_id, currentFilePath.value, direction)
      if (res.data.success) {
        showToast(`图片已${directionText}90度并保存`, 'success')
        const timestamp = Date.now()
        cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        previewUrl.value = originalPreviewUrl.value
        canRestore.value = true
        hasEdits.value = false
        canvasCtx = null
        scale.value = 1
        offsetX.value = 0
        offsetY.value = 0
      } else {
        showToast(`${directionText}失败: ${res.data.message}`, 'error')
      }
    } catch (err) {
      showToast(`${directionText}失败: ${err.response?.data?.detail || err.message}`, 'error')
    } finally {
      isRotating.value = false
    }
  }

  // ============================================================
  // 图片重绘
  // ============================================================
  async function redrawCurrentImage(direction) {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：与旋转同口径（生成PDF期间重绘同样互相踩）
    if (isBusy.value) {
      showToast('正在处理中，请等待完成后再操作', 'warning')
      return
    }
    if (!currentTask.value || !currentFilePath.value) {
      showToast('请先选择图片', 'warning')
      return
    }
    if (isRedrawing.value) return

    if (hasEdits.value) {
      pendingAction.value = () => doRedrawCurrentImage(direction)
      showUnsavedWarning.value = true
      return
    }

    await doRedrawCurrentImage(direction)
  }

  async function doRedrawCurrentImage(direction) {
    if (isRedrawing.value) return

    isRedrawing.value = true
    const directionText = direction === 'enhance' ? '强化' : '弱化'

    try {
      const res = await api.redrawImage(currentTask.value.task_id, currentFilePath.value, direction, redrawStep.value)
      if (res.data.success) {
        showToast(`图片${directionText}完成`, 'success')
        const timestamp = Date.now()
        cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        previewUrl.value = originalPreviewUrl.value
        canRestore.value = true
        hasEdits.value = false
        canvasCtx = null
        scale.value = 1
        offsetX.value = 0
        offsetY.value = 0
      } else {
        showToast(`${directionText}失败: ${res.data.message}`, 'error')
      }
    } catch (err) {
      showToast(`${directionText}失败: ${err.response?.data?.detail || err.message}`, 'error')
    } finally {
      isRedrawing.value = false
    }
  }

  function handleRedrawEnhance() {
    redrawCurrentImage('enhance')
  }

  function handleRedrawWeaken() {
    redrawCurrentImage('weaken')
  }

  function handleBatchRedraw(direction) {
    if (hasEdits.value) {
      pendingAction.value = () => startBatchRedraw(direction)
      showUnsavedWarning.value = true
      return
    }
    startBatchRedraw(direction)
  }

  async function startBatchRedraw(direction) {
    if (!currentTask.value || !canBatchClean.value) return

    const node = effectiveDirectoryNode.value
    const dirPath = effectiveDirectoryPath.value
    if (!node || node.type !== 'directory') {
      showToast('请选择一个目录或目录中的图片', 'warning')
      return
    }

    batchRedrawOriginalDirPath = dirPath

    try {
      const res = await api.batchRedraw(currentTask.value.task_id, dirPath, direction, redrawStep.value)
      if (res.data.success) {
        const directionText = direction === 'enhance' ? '批量强化' : '批量弱化'
        showToast(`开始${directionText}: ` + node.name, 'info')
        isBatchRedrawing.value = true
        showBatchRedrawProgress.value = true
        batchRedrawElapsed.value = 0
        startBatchRedrawPolling()
        startBatchRedrawTimer()
      }
    } catch (err) {
      showToast('启动批量重绘失败: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  function startBatchRedrawPolling() {
    if (batchRedrawTimer.value) clearInterval(batchRedrawTimer.value)
    // xuechong 2026-07-03 网络错误重试计数，连续失败3次才停止轮询
    let retryCount = 0
    const MAX_RETRIES = 3

    batchRedrawTimer.value = setInterval(async () => {
      if (!currentTask.value) {
        stopBatchRedrawPolling()
        return
      }
      try {
        const res = await api.getBatchRedrawStatus(currentTask.value.task_id)
        // xuechong 2026-07-03 请求成功后重置重试计数
        retryCount = 0
        batchRedrawStatus.value = res.data

        if (['completed', 'failed'].includes(res.data.status)) {
          stopBatchRedrawPolling()
          stopBatchRedrawTimer()
          isBatchRedrawing.value = false

          if (batchRedrawOriginalDirPath) {
            selectedPath.value = batchRedrawOriginalDirPath
          }

          if (res.data.status === 'completed') {
            showToast('批量重绘完成！', 'success')
            if (currentFilePath.value) {
              const timestamp = Date.now()
              originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
              previewUrl.value = originalPreviewUrl.value
              cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
            }
          } else {
            showErrorModal('批量重绘失败: ' + res.data.message, res.data.error_detail || '')
          }
        }
      } catch (err) {
        retryCount++
        devLog('error', '[批量重绘] 轮询失败 (第' + retryCount + '次):', err)
        // xuechong 2026-07-03 连续失败才停止，容忍瞬时网络抖动
        if (retryCount >= MAX_RETRIES) {
          stopBatchRedrawPolling()
          showErrorModal('批量重绘轮询异常', '连续' + MAX_RETRIES + '次网络异常，已停止轮询，请检查服务状态')
        }
      }
    }, 5000)
  }

  function stopBatchRedrawPolling() {
    if (batchRedrawTimer.value) {
      clearInterval(batchRedrawTimer.value)
      batchRedrawTimer.value = null
    }
  }

  function startBatchRedrawTimer() {
    batchRedrawElapsed.value = 0
    if (batchRedrawElapsedTimer.value) clearInterval(batchRedrawElapsedTimer.value)
    batchRedrawElapsedTimer.value = setInterval(() => { batchRedrawElapsed.value++ }, 1000)
  }

  function stopBatchRedrawTimer() {
    if (batchRedrawElapsedTimer.value) {
      clearInterval(batchRedrawElapsedTimer.value)
      batchRedrawElapsedTimer.value = null
    }
  }

  function closeBatchRedrawProgress() {
    showBatchRedrawProgress.value = false
    batchRedrawStatus.value = { status: 'idle', progress: 0, current_file: '', message: '' }
  }

  // ============================================================
  // 保存修图和还原
  // ============================================================
  async function saveManualEdit() {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：生成PDF期间保存会改动正被合成的文件。
    // 此处必须有可见反馈：未保存弹窗的"保存并继续"走这里，静默拦截会让用户以为点击失灵
    if (isBusy.value) {
      showToast('正在处理中，请等待完成后再保存', 'warning')
      return
    }
    const { canvas } = getCanvasElements()
    if (!hasEdits.value || !canvas || !currentTask.value || !currentFilePath.value) {
      showToast('没有需要保存的修改', 'warning')
      return
    }

    showLoading.value = true
    loadingMessage.value = '正在保存修图结果...'

    try {
      const imageData = canvas.toDataURL('image/png')
      const res = await api.saveManualEdit(currentTask.value.task_id, currentFilePath.value, imageData)

      if (res.data.success) {
        showToast('修图已保存', 'success')
        hasEdits.value = false
        canRestore.value = true
        const timestamp = Date.now()
        cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        previewUrl.value = originalPreviewUrl.value
      } else {
        showToast('保存失败: ' + res.data.message, 'error')
      }
    } catch (err) {
      showToast('保存失败: ' + (err.response?.data?.detail || err.message), 'error')
    } finally {
      showLoading.value = false
    }
  }

  function confirmRestoreImage() {
    if (!canRestore.value) {
      showToast('没有可还原的备份', 'warning')
      return
    }
    showRestoreConfirm.value = true
  }

  async function doRestoreImage() {
    showRestoreConfirm.value = false
    if (!currentTask.value || !currentFilePath.value) {
      showToast('操作无效', 'error')
      return
    }

    showLoading.value = true
    loadingMessage.value = '正在还原图片...'

    try {
      const res = await api.restoreImage(currentTask.value.task_id, currentFilePath.value)
      if (res.data.success) {
        showToast('图片已还原为原图', 'success')
        canRestore.value = false
        hasEdits.value = false
        canvasCtx = null
        const timestamp = Date.now()
        const imageUrl = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        cleanedPreviewUrl.value = imageUrl
        originalPreviewUrl.value = imageUrl
        previewUrl.value = imageUrl
        isLoadingCleaned.value = false
      } else {
        showToast('还原失败: ' + res.data.message, 'error')
      }
    } catch (err) {
      showToast('还原失败: ' + (err.response?.data?.detail || err.message), 'error')
    } finally {
      showLoading.value = false
    }
  }

  // ============================================================
  // 单张修图
  // ============================================================
  async function cleanSingleImage() {
    if (!currentTask.value || !currentFilePath.value) {
      showToast('请先选择图片', 'warning')
      return
    }

    showLoading.value = true
    loadingMessage.value = '正在修图净化...'

    try {
      const res = await api.cleanFile(currentFilePath.value, currentTask.value.task_id)
      if (res.data.success) {
        showToast('图片修图完成', 'success')
        const timestamp = Date.now()
        cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
        previewUrl.value = originalPreviewUrl.value
        canRestore.value = true
        hasEdits.value = false
        canvasCtx = null
      } else {
        showToast('修图失败: ' + (res.data.message || '未知错误'), 'error')
      }
    } catch (err) {
      showToast('修图失败: ' + (err.response?.data?.detail || err.message), 'error')
    } finally {
      showLoading.value = false
    }
  }

  function handleSingleClean() {
    // xuechong 2026-10-11 研发BUG-0073 处理期间冻结：与 canSingleClean 的 isBusy 判定同口径，
    // 菜单若在忙碌开始前已展开，菜单项点击在此兜底拦截
    if (isBusy.value) {
      showToast('正在处理中，请等待完成后再操作', 'warning')
      return
    }
    if (hasEdits.value) {
      pendingAction.value = () => cleanSingleImage()
      showUnsavedWarning.value = true
      return
    }
    cleanSingleImage()
  }

  // ============================================================
  // 一键修图
  // ============================================================
  async function startBatchClean() {
    if (!currentTask.value || !canBatchClean.value) {
      // V3.1.01 xuechong 2026-07-25 诊断：告诉用户为什么不能修图
      // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
      // diagnose 返回空时也必须给可见反馈，杜绝"点击无反应无提示"的静默失败
      const reason = diagnoseBatchClean()
      console.warn('[一键修图] 无法启动:', reason || '未知原因',
                   '| 任务状态:', currentTask.value?.status, '| 选择路径:', selectedPath.value)
      showToast('无法启动修图: ' + (reason || '当前状态不满足启动条件'), 'warning')
      return
    }

    const node = effectiveDirectoryNode.value
    const dirPath = effectiveDirectoryPath.value
    if (!node || node.type !== 'directory') {
      showToast('请选择一个目录或目录中的图片', 'warning')
      return
    }

    // 检查是否为包含子目录的一级文件夹
    if (hasSubDirectories(node)) {
      const leafDirs = getAllLeafDirectories(node)
      if (leafDirs.length === 0) {
        showToast('选中的目录下没有可处理的图片文件夹', 'warning')
        return
      }
      await startRecursiveBatchClean(leafDirs)
      return
    }

    batchCleanOriginalDirPath = dirPath

    try {
      const res = await api.batchClean(currentTask.value.task_id, dirPath)
      if (res.data.success) {
        showToast('开始一键修图: ' + node.name, 'info')
        isBatchCleaning.value = true
        showBatchCleanProgress.value = true
        batchCleanElapsed.value = 0
        startBatchCleanPolling()
        startBatchCleanTimer()
      }
    } catch (err) {
      showToast('启动一键修图失败: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  // 递归批量修图：遍历所有叶目录，逐个执行一键修图→自动生成PDF
  async function startRecursiveBatchClean(leafDirs) {
    const processList = [...leafDirs]
    recursiveCleanQueue.value = processList
    recursiveCleanTotal.value = processList.length
    recursiveCleanIndex.value = 0

    isBatchCleaning.value = true
    showBatchCleanProgress.value = true
    batchCleanElapsed.value = 0
    startBatchCleanTimer()

    showToast(`开始一键修图 ${processList.length} 个文件夹`, 'info')

    for (let i = 0; i < processList.length; i++) {
      if (!currentTask.value) break
      const dir = processList[i]
      recursiveCleanIndex.value = i

      batchCleanStatus.value = {
        status: 'processing',
        progress: 0,
        current_file: '',
        current_path: '',
        message: `正在修图: ${dir.name} (${i + 1}/${processList.length})`,
        images_cleaned: false
      }

      try {
        const res = await api.batchClean(currentTask.value.task_id, dir.path)
        if (!res.data.success) {
          showErrorModal(`${dir.name} 修图启动失败`, res.data.message || '未知错误')
          isBatchCleaning.value = false
          stopBatchCleanTimer()
          return
        }
        // 等待当前文件夹修图完成
        await waitForBatchCleanComplete()
      } catch (err) {
        showErrorModal(`${dir.name} 修图失败`, err.response?.data?.detail || err.message)
        isBatchCleaning.value = false
        stopBatchCleanTimer()
        return
      }

      // 修图完成，自动生成PDF（不弹确认框）；同§5.1口径：自动链生成不带页码，页码由form-in步骤7组卷时添加
      batchCleanStatus.value.message = `${dir.name} 修图完成，正在生成PDF...`
      try {
        const pdfRes = await processUploadWithBusyRetry(currentTask.value.task_id, pageNoParam(false), dir.path)  // 研发BUG-0074：默认模式听复选框（此前固定不加），嵌入模式保持不加
        if (!pdfRes.data.already_completed) {
          await waitForProcessComplete()
        }
      } catch (err) {
        showErrorModal(`${dir.name} PDF生成失败`, err.response?.data?.detail || err.message)
      }
    }

    stopBatchCleanTimer()
    isBatchCleaning.value = false
    batchCleanStatus.value.status = 'completed'
    batchCleanStatus.value.message = `全部完成: ${processList.length} 个文件夹`

    // 刷新文件树和下载历史
    if (currentTask.value?.task_id) {
      await loadFileTree(currentTask.value.task_id)
    }
    await loadDownloadHistory()

    // 更新步骤状态
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态修复
    // ① 步骤3（生成PDF）补 completed——递归流程中每个目录的 PDF 已自动生成，原实现跳过 3 导致步骤条误导
    // ② 记录批量完成摘要，驱动生成面板显示"全部完成+打开转换记录"而非"生成PDF"按钮（PDF 已全部生成，按钮纯属误导）
    stepStatus.value = { 1: 'completed', 2: 'completed', 3: 'completed', 4: 'completed' }
    batchGenerateSummary.value = { folders: processList.length }
    // xuechong 2026-08-07 研发BUG-0016 修复递归批量修图完成后不切换面板的问题
    if (operationMode.value === 'manual') {
      manualActivePanel.value = 'generate'
    } else {
      currentStep.value = 4
    }
    // 批处理生成多个PDF，不显示单一"下载PDF"按钮（task["merged_pdf"]只指向最后一个）
    // 引导用户通过"转换记录"分别下载各文件夹的PDF
    showToast(`一键修图并生成PDF完成！共处理 ${processList.length} 个文件夹，请在'转换记录'中下载`, 'success')
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  function waitForBatchCleanComplete() {
    return new Promise((resolve, reject) => {
      let lastCompletedPath = ''
      let lastProcessedCount = 0
      // xuechong 2026-07-03 网络错误重试计数，连续失败3次才reject
      let retryCount = 0
      const MAX_RETRIES = 3
      const checkInterval = setInterval(async () => {
        if (!currentTask.value) {
          clearInterval(checkInterval)
          reject(new Error('任务不存在'))
          return
        }
        try {
          const res = await api.getBatchCleanStatus(currentTask.value.task_id)
          // xuechong 2026-07-03 请求成功后重置重试计数
          retryCount = 0
          batchCleanStatus.value = res.data

          // 每处理完一张图片就更新修图区预览
          const currentPath = res.data.current_path
          const processedCount = res.data.processed_files || 0
          if (currentPath && processedCount > lastProcessedCount && res.data.status === 'processing') {
            lastProcessedCount = processedCount
            lastCompletedPath = currentPath
            await updateBatchCleanPreview(currentPath)
          }

          if (['completed', 'failed', 'cancelled'].includes(res.data.status)) {
            clearInterval(checkInterval)
            if (res.data.status === 'completed') {
              resolve()
            } else if (res.data.status === 'cancelled') {
              reject(new Error(res.data.message || '修图已取消'))
            } else {
              reject(new Error(res.data.message || '修图失败'))
            }
          }
        } catch (err) {
          retryCount++
          devLog('error', '[批量修图等待] 轮询失败 (第' + retryCount + '次):', err)
          // xuechong 2026-07-03 连续失败才reject，容忍瞬时网络抖动
          if (retryCount >= MAX_RETRIES) {
            clearInterval(checkInterval)
            reject(new Error('连续' + MAX_RETRIES + '次网络异常，已停止轮询'))
          }
        }
      }, 5000)
    })
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  function waitForProcessComplete() {
    return new Promise((resolve, reject) => {
      // xuechong 2026-07-03 网络错误重试计数，连续失败3次才reject
      let retryCount = 0
      const MAX_RETRIES = 3
      const checkInterval = setInterval(async () => {
        if (!currentTask.value) {
          clearInterval(checkInterval)
          reject(new Error('任务不存在'))
          return
        }
        try {
          const res = await api.getUploadTask(currentTask.value.task_id)
          // xuechong 2026-07-03 请求成功后重置重试计数
          retryCount = 0
          if (res.data.status === 'completed' || res.data.status === 'uploaded') {
            clearInterval(checkInterval)
            resolve()
          } else if (res.data.status === 'error' || res.data.status === 'failed') {
            clearInterval(checkInterval)
            reject(new Error(res.data.message || '处理失败'))
          }
        } catch (err) {
          retryCount++
          devLog('error', '[处理等待] 轮询失败 (第' + retryCount + '次):', err)
          // xuechong 2026-07-03 连续失败才reject，容忍瞬时网络抖动
          if (retryCount >= MAX_RETRIES) {
            clearInterval(checkInterval)
            reject(new Error('连续' + MAX_RETRIES + '次网络异常，已停止轮询'))
          }
        }
      }, 5000)
    })
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // resumeOnly：仅恢复修图进度展示（嵌入页接手form-in驱动任务时传true），修图完成后
  // 不自动生成PDF，避免与智能收集整理页双端驱动重复处理
  function startBatchCleanPolling(resumeOnly) {
    if (batchCleanTimer.value) clearInterval(batchCleanTimer.value)
    let lastProcessedCount = 0
    // xuechong 2026-07-03 网络错误重试计数，连续失败3次才停止轮询
    let retryCount = 0
    const MAX_RETRIES = 3

    batchCleanTimer.value = setInterval(async () => {
      if (!currentTask.value) {
        stopBatchCleanPolling()
        return
      }
      try {
        const res = await api.getBatchCleanStatus(currentTask.value.task_id)
        // xuechong 2026-07-03 请求成功后重置重试计数
        retryCount = 0
        batchCleanStatus.value = res.data

        // 用 processed_files 计数判断是否有新完成的图片（比 current_path 更可靠）
        const processedCount = res.data.processed_files || 0
        if (res.data.current_path && processedCount > lastProcessedCount && res.data.status === 'processing') {
          lastProcessedCount = processedCount
          await updateBatchCleanPreview(res.data.current_path)
        }

        // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        // idle 终止：服务重启后内存态丢失返回idle，停止轮询并引导从未完成任务恢复
        if (res.data.status === 'idle') {
          stopBatchCleanPolling()
          stopBatchCleanTimer()
          isBatchCleaning.value = false
          showToast('修图状态丢失（服务可能已重启），请点击右上角"未完成任务"恢复续跑', 'warning')
          return
        }

        if (['completed', 'failed', 'cancelled'].includes(res.data.status)) {
          stopBatchCleanPolling()
          stopBatchCleanTimer()
          isBatchCleaning.value = false

          if (batchCleanOriginalDirPath) {
            selectedPath.value = batchCleanOriginalDirPath
          }

          if (res.data.status === 'completed') {
            if (currentFilePath.value) {
              const timestamp = Date.now()
              originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
              previewUrl.value = originalPreviewUrl.value
              cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentFilePath.value) + `&t=${timestamp}`
            }
            const newStatus = { ...stepStatus.value }
            newStatus[2] = 'completed'
            stepStatus.value = newStatus
            // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
            // resumeOnly：仅恢复展示（form-in驱动的任务），修图完成只更新状态与预览，
            // 不自动生成PDF（生成由智能收集整理页统一驱动），也不切换到生成PDF面板
            if (resumeOnly) {
              showToast('图片修图已完成，PDF生成由智能收集整理页统一驱动', 'info')
              return
            }
            // 修图完成后自动生成PDF，不再弹出确认对话框
            showToast('自动修图完成，正在生成PDF...', 'success')
            const genStatus = { ...stepStatus.value }
            genStatus[4] = 'active'
            stepStatus.value = genStatus
            // xuechong 2026-08-07 研发BUG-0016 移除多余条件判断，确保面板一定切换
            console.log('[一键修图→PDF] 修图完成，准备切换面板并生成PDF', {
              operationMode: operationMode.value,
              currentStep: currentStep.value,
              selectedPath: selectedPath.value,
              taskId: currentTask.value?.task_id,
              taskStatus: currentTask.value?.status
            })
            if (operationMode.value === 'manual') {
              // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
              // 步骤1（恢复态）发起批量修图的补跳：
              // 手动模式下 currentStep=1 时导入视图优先渲染，仅切 manualActivePanel 不会发生
              // 可见的页面跳转；先推进到步骤2再切生成面板（修复"修图完不跳生成PDF"）
              if (currentStep.value === 1) {
                currentStep.value = 2
              }
              manualActivePanel.value = 'generate'
              // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
              // 统一完成视图：单文件夹一键修图自动生成PDF与递归批量同口径。挂起标记
              // 在PDF生成轮询完成时消费（此刻才切"全部完成"视图并弹转换记录，避免
              // 生成开始前就弹记录）。此前单文件夹（上传图片扁平结构）结束于"预览/下载"
              // 视图、多文件夹（上传目录嵌套结构）结束于"全部完成"视图，同一操作两种结局
              batchCleanAutoGenPending.value = true
              // 手动模式保持原行为：经确认弹窗再批量生成
              startProcess()
            } else {
              currentStep.value = 4
              // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
              // 自动模式（无人值守）修图完成后走自动生成入口：含子文件夹时直接批量生成，不弹确认框
              startProcessAuto()
            }
          } else if (res.data.status === 'cancelled') {
            showToast(res.data.message || '修图已停止', 'info')
          } else {
            showErrorModal('一键修图失败: ' + res.data.message, res.data.error_detail || '')
          }
        }
      } catch (err) {
        retryCount++
        devLog('error', '[一键修图] 轮询失败 (第' + retryCount + '次):', err)
        // xuechong 2026-07-03 连续失败才停止，容忍瞬时网络抖动
        if (retryCount >= MAX_RETRIES) {
          stopBatchCleanPolling()
          showErrorModal('一键修图轮询异常', '连续' + MAX_RETRIES + '次网络异常，已停止轮询，请检查服务状态')
        }
      }
    }, 5000)
  }

  function stopBatchCleanPolling() {
    if (batchCleanTimer.value) {
      clearInterval(batchCleanTimer.value)
      batchCleanTimer.value = null
    }
  }

  function startBatchCleanTimer() {
    batchCleanElapsed.value = 0
    if (batchCleanElapsedTimer.value) clearInterval(batchCleanElapsedTimer.value)
    batchCleanElapsedTimer.value = setInterval(() => { batchCleanElapsed.value++ }, 1000)
  }

  function stopBatchCleanTimer() {
    if (batchCleanElapsedTimer.value) {
      clearInterval(batchCleanElapsedTimer.value)
      batchCleanElapsedTimer.value = null
    }
  }

  async function stopBatchClean() {
    if (!currentTask.value) return

    try {
      await api.cancelTask(currentTask.value.task_id)
    } catch (err) {
      // 即使取消请求失败也要停止前端轮询
      devLog('error', '[一键修图] 取消请求失败:', err)
    }

    stopBatchCleanPolling()
    stopBatchCleanTimer()
    isBatchCleaning.value = false
    batchCleanStatus.value.status = 'cancelled'

    const processed = batchCleanStatus.value.processed_files || 0
    const currentFile = batchCleanStatus.value.current_file || ''
    if (currentFile && batchCleanOriginalDirPath) {
      selectedPath.value = batchCleanOriginalDirPath
    }
    showToast(`修图已停止${processed ? ' (' + processed + ' 张已完成)' : ''}`, 'info')
  }

  function closeBatchCleanProgress() {
    showBatchCleanProgress.value = false
    batchCleanStatus.value = {
      status: 'idle', progress: 0, current_file: '', current_path: '', message: '', images_cleaned: false
    }
  }

  async function updateBatchCleanPreview(currentPath) {
    if (!currentTask.value || !isBatchCleaning.value || !currentPath) return

    selectedPath.value = currentPath
    currentFilePath.value = currentPath
    const timestamp = Date.now()
    originalPreviewUrl.value = api.getBackupPreviewUrl(currentTask.value.task_id, currentPath) + `&t=${timestamp}`
    previewUrl.value = originalPreviewUrl.value
    cleanedPreviewUrl.value = api.getPreviewUrl(currentTask.value.task_id, currentPath) + `&t=${timestamp}`
    isLoadingCleaned.value = false
    hasEdits.value = false
    canRestore.value = true
  }

  // ============================================================
  // 生成PDF
  // ============================================================
  async function startProcess() {
    console.log('[startProcess] 入口', {
      hasTask: !!currentTask.value,
      taskId: currentTask.value?.task_id,
      selectedPath: selectedPath.value
    })
    if (!currentTask.value) {
      console.warn('[startProcess] currentTask 为空，直接返回')
      return
    }

    if (!selectedPath.value) {
      console.warn('[startProcess] selectedPath 为空')
      showToast('请先在左侧文件列表中选择一个目录或图片文件', 'warning')
      return
    }

    const node = effectiveDirectoryNode.value
    const dirPath = effectiveDirectoryPath.value
    console.log('[startProcess] 路径解析', {
      dirPath,
      hasNode: !!node,
      nodeType: node?.type,
      isLeaf: node ? isLeafDirectory(node) : null
    })

    if (!node) {
      console.warn('[startProcess] node 为空，selectedPath 无法在文件树中找到')
      showToast('未找到有效的目录，请重新选择', 'warning')
      return
    }

    if (!isLeafDirectory(node)) {
      const hasSubDirs = node.children?.some(child => child.type === 'directory')
      if (hasSubDirs) {
        const leafDirs = getAllLeafDirectories(node)
        if (leafDirs.length === 0) {
          showToast('选中的目录下没有可处理的图片文件夹', 'warning')
          return
        }
        console.log('[startProcess] 非叶目录，打开批量PDF弹窗', { leafCount: leafDirs.length })
        batchPdfList.value = leafDirs
        showBatchPdfModal.value = true
        return
      }
      showToast('选中的目录为空，没有图片文件可以处理', 'warning')
      return
    }

    console.log('[startProcess] 调用 processSingleDirectory', { dirPath, folderName: node.name })
    await processSingleDirectory(dirPath, node.name)
  }

  async function processSingleDirectory(dirPath, folderName) {
    showDownloadBtn.value = false
    try {
      console.log('[processSingleDirectory] 调用 api.processUpload', {
        taskId: currentTask.value.task_id,
        dirPath,
        addPageNumber: addPageNumber.value
      })
      // 研发BUG-0074：页码统一，与其他链路同走 pageNoParam（默认模式听复选框，嵌入模式保持历史行为=加页码）
      const res = await processUploadWithBusyRetry(currentTask.value.task_id, pageNoParam(true), dirPath)
      console.log('[processSingleDirectory] API响应', {
        success: res.data.success,
        already_completed: res.data.already_completed,
        message: res.data.message
      })

      if (res.data.already_completed) {
        showToast('该目录已处理完成，可以直接下载', 'success')
        currentTask.value.status = 'completed'
        // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
        // 修图自动生成链遇到已生成目录：消费挂起标记按批量口径结束（View B）；
        // 普通"生成PDF"按钮路径（无标记）保持"预览/下载"视图
        if (batchCleanAutoGenPending.value) {
          batchCleanAutoGenPending.value = false
          batchGenerateSummary.value = { folders: 1 }
        } else {
          batchGenerateSummary.value = null
          showDownloadBtn.value = true
        }
        return
      }

      currentTask.value.status = 'processing'
      currentTask.value.message = '正在处理...'
      currentTask.value.progress = 0
      showToast('开始处理: ' + folderName, 'info')
      console.log('[processSingleDirectory] 启动轮询 startPolling')
      startPolling()
    } catch (err) {
      console.error('[processSingleDirectory] API调用失败', err.response?.status, err.response?.data || err.message)
      showToast('启动处理失败: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  // 批量PDF
  function closeBatchPdfModal() {
    showBatchPdfModal.value = false
    batchPdfList.value = []
  }

  async function startBatchPdfProcess() {
    if (batchPdfList.value.length === 0 || !currentTask.value?.task_id) return

    const processList = [...batchPdfList.value]
    showBatchPdfModal.value = false
    batchPdfList.value = []

    isBatchPdfProcessing.value = true
    showBatchPdfProgressModal.value = true
    batchPdfProgress.value = {
      current: 0, total: processList.length, currentFolder: '', currentProgress: 0, currentMessage: '', status: 'processing'
    }

    showToast(`开始批量处理 ${processList.length} 个文件夹`, 'info')

    try {
      for (let i = 0; i < processList.length; i++) {
        const item = processList[i]
        batchPdfProgress.value.current = i
        batchPdfProgress.value.currentFolder = item.name
        batchPdfProgress.value.currentProgress = 0
        batchPdfProgress.value.currentMessage = '准备处理...'

        try {
          // xuechong 2026-09-29 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
          // 自动链生成PDF固定不带页码（需求§5.1：生成环节不带页码，页码在form-in步骤7智能组卷环节添加，避免双重页码）
          const res = await processUploadWithBusyRetry(currentTask.value.task_id, pageNoParam(false), item.path)  // 研发BUG-0074：默认模式听复选框（此前固定不加），嵌入模式保持不加
          if (res.data.already_completed) {
            batchPdfProgress.value.currentProgress = 100
            batchPdfProgress.value.currentMessage = '已完成（跳过）'
            batchPdfProgress.value.current = i + 1
            continue
          }
          await waitForProcessCompleteWithProgress()
          batchPdfProgress.value.current = i + 1
        } catch (err) {
          showErrorModal(`${item.name} 处理失败`, err.response?.data?.detail || err.message)
          batchPdfProgress.value.status = 'failed'
          isBatchPdfProcessing.value = false
          return
        }
      }

      batchPdfProgress.value.status = 'completed'
      isBatchPdfProcessing.value = false
      showToast(`批量处理完成！共处理 ${processList.length} 个文件夹，请在'转换记录'中下载`, 'success')

      if (currentTask.value?.task_id) {
        await loadFileTree(currentTask.value.task_id)
      }
      await loadDownloadHistory()

      // 更新步骤状态
      stepStatus.value = { 1: 'completed', 2: 'completed', 4: 'completed' }
    } catch (err) {
      devLog('error', '[批量PDF] 处理异常:', err)
      batchPdfProgress.value.status = 'failed'
      batchPdfProgress.value.currentMessage = '处理异常: ' + (err?.response?.data?.detail || err.message || '未知错误')
      isBatchPdfProcessing.value = false
      showErrorModal('批量PDF处理异常', err?.response?.data?.detail || err.message || '未知错误')
    }
  }

  function closeBatchPdfProgressModal() {
    showBatchPdfProgressModal.value = false
    isBatchPdfProcessing.value = false
    batchPdfProgress.value = {
      current: 0, total: 0, currentFolder: '', currentProgress: 0, currentMessage: '', status: 'idle'
    }
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 开始处理遇"任务正在处理中"（上一目录尚未处理完/另一入口已在处理同一任务）不再弹"处理失败"
  // 中断批量链：等待任务脱离处理态后自动重试同一目录，最多等待3轮，仍忙才走失败分支
  async function processUploadWithBusyRetry(taskId, pageNo, selectedPath, maxBusyWaits = 3) {
    let busyWaits = 0
    while (true) {
      try {
        return await api.processUpload(taskId, pageNo, selectedPath)
      } catch (err) {
        const detail = err.response?.data?.detail || err.message || ''
        if (detail.indexOf('任务正在处理中') === -1 || busyWaits >= maxBusyWaits) {
          throw err
        }
        busyWaits++
        showToast(`任务正在处理中，等待上一处理完成后自动继续（第${busyWaits}/${maxBusyWaits}次等待）`, 'info')
        await waitForTaskNotProcessing()
      }
    }
  }

  // 等待任务脱离processing状态（5秒轮询，completed/failed等状态即放行；连续网络异常或超时则拒绝）
  function waitForTaskNotProcessing(maxPolls = 60) {
    return new Promise((resolve, reject) => {
      let pollCount = 0
      let errCount = 0
      const timer = setInterval(async () => {
        pollCount++
        try {
          const res = await api.getUploadTask(currentTask.value.task_id)
          errCount = 0
          if (res.data.status !== 'processing') {
            clearInterval(timer)
            resolve(res.data.status)
          }
        } catch (err) {
          errCount++
          if (errCount >= 3) {
            clearInterval(timer)
            reject(err)
          }
        }
        if (pollCount >= maxPolls) {
          clearInterval(timer)
          reject(new Error('等待任务空闲超时（5分钟）'))
        }
      }, 5000)
    })
  }

  function waitForProcessCompleteWithProgress() {
    return new Promise((resolve, reject) => {
      // xuechong 2026-07-03 网络错误重试计数，连续失败3次才reject
      let retryCount = 0
      const MAX_RETRIES = 3
      const checkInterval = setInterval(async () => {
        try {
          const res = await api.getUploadTask(currentTask.value.task_id)
          // xuechong 2026-07-03 请求成功后重置重试计数
          retryCount = 0
          batchPdfProgress.value.currentProgress = res.data.progress || 0
          batchPdfProgress.value.currentMessage = res.data.message || ''
          if (res.data.status === 'completed' || res.data.status === 'uploaded') {
            batchPdfProgress.value.currentProgress = 100
            batchPdfProgress.value.currentMessage = '已完成'
            clearInterval(checkInterval)
            resolve()
          } else if (res.data.status === 'error' || res.data.status === 'failed') {
            const errMsg = res.data.message || res.data.error_detail || '处理失败'
            batchPdfProgress.value.currentMessage = errMsg
            clearInterval(checkInterval)
            showErrorModal('处理失败', errMsg)
            reject(new Error(errMsg))
          }
        } catch (err) {
          retryCount++
          devLog('error', '[处理进度等待] 轮询失败 (第' + retryCount + '次):', err)
          // xuechong 2026-07-03 连续失败才reject，容忍瞬时网络抖动
          if (retryCount >= MAX_RETRIES) {
            clearInterval(checkInterval)
            batchPdfProgress.value.status = 'failed'
            batchPdfProgress.value.currentMessage = '连续' + MAX_RETRIES + '次网络异常，已停止轮询'
            showErrorModal('处理异常', '连续' + MAX_RETRIES + '次网络异常，请检查服务状态')
            reject(new Error('连续' + MAX_RETRIES + '次网络异常'))
          }
        }
      }, 5000)
    })
  }

  // 计时器
  function formatElapsedTime(seconds) {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  }

  function startProcessTimer() {
    processElapsed.value = 0
    if (processTimer.value) clearInterval(processTimer.value)
    processTimer.value = setInterval(() => { processElapsed.value++ }, 1000)
  }

  function stopProcessTimer() {
    if (processTimer.value) {
      clearInterval(processTimer.value)
      processTimer.value = null
    }
  }

  // xuechong 2026-07-03 轮询容错：增加重试机制+间隔调整为5000ms
  function startPolling() {
    if (pollTimer.value) clearInterval(pollTimer.value)
    startProcessTimer()
    // xuechong 2026-07-03 网络错误重试计数，连续失败3次才停止轮询
    let retryCount = 0
    const MAX_RETRIES = 3

    pollTimer.value = setInterval(async () => {
      if (!currentTask.value) {
        clearInterval(pollTimer.value)
        return
      }
      try {
        const res = await api.getUploadTask(currentTask.value.task_id)
        // xuechong 2026-07-03 请求成功后重置重试计数
        retryCount = 0
        currentTask.value = res.data

        if (['completed', 'failed'].includes(res.data.status)) {
          clearInterval(pollTimer.value)
          pollTimer.value = null
          stopProcessTimer()

          if (res.data.status === 'completed') {
            showToast('处理完成！', 'success')
            // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
            // 完成视图三分：批量摘要已在（递归链）或单文件夹修图自动生成挂起（消费标记，
            // 切"全部完成"视图并经watch自动弹出转换记录）→ 不点亮下载按钮；普通"生成PDF"
            // 按钮（无修图）→ "预览/下载"视图。消除同一操作两种结束页的随机感
            if (batchGenerateSummary.value) {
              // 递归批量链：摘要已驱动"全部完成"视图
            } else if (batchCleanAutoGenPending.value) {
              batchCleanAutoGenPending.value = false
              batchGenerateSummary.value = { folders: 1 }
            } else {
              showDownloadBtn.value = true
            }
            loadDownloadHistory()
          } else {
            showErrorModal('处理失败: ' + res.data.message, res.data.error_detail || '')
            showDownloadBtn.value = false
          }
        }
      } catch (err) {
        retryCount++
        devLog('error', '[轮询] 失败 (第' + retryCount + '次):', err)
        // xuechong 2026-07-03 连续失败才停止，容忍瞬时网络抖动
        if (retryCount >= MAX_RETRIES) {
          clearInterval(pollTimer.value)
          pollTimer.value = null
          showErrorModal('处理轮询异常', '连续' + MAX_RETRIES + '次网络异常，已停止轮询，请检查服务状态')
        }
      }
    }, 5000)
  }

  // ============================================================
  // 下载和预览
  // ============================================================
  async function downloadResult() {
    if (!currentTask.value) {
      showToast('没有可下载的任务', 'warning')
      return
    }

    const taskId = currentTask.value.task_id
    showToast('准备下载...', 'info')

    try {
      const response = await api.downloadResultBlob(taskId)

      let filename = `${taskId}.pdf`
      const contentDisposition = response.headers['content-disposition']
      if (contentDisposition) {
        const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/i)
        if (utf8Match) {
          filename = decodeURIComponent(utf8Match[1])
        } else {
          const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
          if (match) filename = match[1].replace(/['"]/g, '')
        }
      }

      const blob = response.data
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)

      showToast('下载完成', 'success')
    } catch (err) {
      showToast('下载失败: ' + err.message, 'error')
    }
  }

  function previewResult() {
    if (!currentTask.value) {
      showToast('没有可预览的PDF', 'warning')
      return
    }
    const url = api.getPreviewPdfUrl(currentTask.value.task_id)
    window.open(url, '_blank')
  }

  // ============================================================
  // 操作记录
  // ============================================================
  // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 操作记录加载连续失败计数（成功清零）：嵌入模式1秒轮询据此降频——连续失败时不再每秒
  // 轰炸接口与提示，恢复成功自动回到正常轮询节奏
  const downloadHistoryFailStreak = ref(0)

  async function loadDownloadHistory() {
    try {
      const res = await api.getDownloadHistory()
      // xuechong 2026-10-06 研发需求-0164 嵌入会话过滤：转换记录只显示会话期间产生的条目；
      // 演示链记录（source=form-in）恒可见（八步页先上传、嵌入页后打开也能立刻看到，与任务同款）
      downloadHistory.value = (res.data.history || []).filter(item => p_recordInEmbedView(item))
      downloadHistoryFailStreak.value = 0
    } catch (err) {
      devLog('error', '[操作记录] 加载失败:', err)
      downloadHistoryFailStreak.value++
      // xuechong 2026-09-30 同需求：轮询期间反复失败只提示一次（useToast同消息去重后不堆叠），
      // 用户手动点"转换记录/刷新"触发的失败仍会有提示，不静默
      showToast('操作记录加载失败: ' + (err?.response?.data?.detail || err.message), 'error')
    }
  }

  // xuechong 2026-06-01 加载上传历史记录
  async function loadUploadHistory() {
    try {
      const res = await api.getUploadHistory()
      // xuechong 2026-10-06 研发需求-0164 嵌入会话过滤：上传记录只显示会话期间产生的条目；
      // 演示链记录（source=form-in）恒可见（与任务/转换记录同款豁免）
      uploadHistory.value = (res.data.history || []).filter(item => p_recordInEmbedView(item))
    } catch (err) {
      devLog('error', '[上传历史] 加载失败:', err)
    }
  }

  // xuechong 2026-06-01 删除上传历史记录
  async function deleteUploadHistoryItem(taskId) {
    try {
      await api.deleteUploadHistoryItem(taskId)
      await loadUploadHistory()
      showToast('上传记录已删除', 'success')
    } catch (err) {
      showToast('删除失败: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  async function deleteHistoryItem(index) {
    try {
      await api.deleteDownloadHistoryItem(index)
      await loadDownloadHistory()
    } catch (err) {
      devLog('error', '[操作记录] 删除失败:', err)
      showToast('操作记录删除失败: ' + (err?.response?.data?.detail || err.message), 'error')
    }
  }

  // ============================================================
  // 组件卸载时清理所有定时器
  // ============================================================
  onUnmounted(() => {
    // xuechong 2026-06-01 清理上传计时器
    _stopUploadTimer()
    // xuechong 2026-06-01 组件卸载时中止未完成的上传请求
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    const timers = [
      pollTimer, batchCleanTimer, batchCleanElapsedTimer,
      batchRedrawTimer, batchRedrawElapsedTimer, processTimer
    ]
    timers.forEach(t => {
      if (t.value) {
        clearInterval(t.value)
        t.value = null
      }
    })
  })

  // ============================================================
  // 返回所有状态和方法
  // ============================================================
  return {
    // 步骤流程
    currentStep,
    stepStatus,
    goToStep,
    advanceStep,
    goBack,
    resetSteps,
    startAutoProcess,

    // 操作模式
    operationMode,
    manualActivePanel,

    // 模板引用
    folderInput,
    leftContainer,
    rightContainer,

    // 核心状态
    currentTask,
    fileTree,
    selectedPath,
    expandedPaths,
    previewUrl,
    addPageNumber,
    isUploading,
    uploadProgress,
    cancelUpload,  // xuechong 2026-06-01 取消上传方法
    closeUploadModal,  // xuechong 2026-06-01 关闭上传弹窗
    // xuechong 2026-06-01 上传弹窗状态
    showUploadModal,
    uploadModalTitle,
    uploadModalPhase,
    uploadModalCurrentFile,
    uploadModalElapsed,
    uploadModalFolderName,
    uploadModalTotalFiles,
    checkServerActiveTask,  // xuechong 2026-06-01 检查服务器活跃任务
    restoreTaskState,  // xuechong 2026-06-01 恢复任务状态
    // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
    // 未完成任务弹框数据与刷新
    unfinishedTaskList, unfinishedCount, fetchUnfinishedTasks,
    activeTaskList,  // xuechong 2026-06-02 活跃任务列表
    clearTaskIdFromStorage,  // xuechong 2026-06-01 清除存储的 taskId

    // 图片修图
    originalPreviewUrl,
    cleanedPreviewUrl,
    isLoadingCleaned,
    hasEdits,
    canRestore,
    showLoading,
    loadingMessage,
    showRestoreConfirm,
    currentFilePath,
    siblingImages,
    currentImageIndex,
    isRotating,

    // 未保存修改
    showUnsavedWarning,
    showReplaceConfirm,
    pendingAction,

    // 缩放/拖拽
    scale,
    offsetX,
    offsetY,
    isDragging,
    imageStyle,


    // 绘图
    isDrawing,

    // 撤销/重做
    canUndo,
    canRedo,

    // 一键修图
    isBatchCleaning,
    showBatchCleanProgress,
    showBatchCleanConfirmModal,
    batchCleanStatus,
    batchCleanElapsed,
    recursiveCleanQueue,
    recursiveCleanIndex,
    recursiveCleanTotal,

    // 批量PDF
    showBatchPdfModal,
    showBatchPdfProgressModal,
    batchPdfList,
    isBatchPdfProcessing,
    batchPdfProgress,

    // 处理
    processElapsed,
    showDownloadBtn,
    batchGenerateSummary,
    isProcessing,
    isBusy,
    cleaningLocked,  // xuechong 2026-10-11 研发BUG-0073 修图锁定（一键修图/批量修图/批量重绘进行中）
    canProcess,
    canBatchClean,
    canGoPrev,
    canGoNext,

    // 下载历史
    downloadHistory,
    // xuechong 2026-09-30 操作记录连续失败计数（嵌入轮询降频用）
    downloadHistoryFailStreak,
    historyCurrentPage,
    historyPageSize,
    historyTotalPages,
    paginatedHistory,
    // xuechong 2026-06-01 上传历史
    uploadHistory,
    loadUploadHistory,
    deleteUploadHistoryItem,

    // 文件树工具
    findNodeByPath,
    findFirstImage,
    isLeafDirectory,
    hasSubDirectories,
    getAllLeafDirectories,
    selectedNode,
    effectiveDirectoryPath,
    effectiveDirectoryNode,

    // 上传
    uploadFiles,
    handleFolderUpload,
    handleImageUpload,
    loadFileTree,
    confirmReplace,
    cancelReplace,

    // 文件选择
    handleSelect,
    resetEditState,

    // 文件删除
    showDeleteConfirm,
    handleDelete,
    confirmDelete,

    // 图片加载
    onImageLoad,
    onCleanedImageLoad,
    initEditCanvas,

    // 目录展开
    handleToggle,
    expandAll,
    collapseAll,

    // 缩放/拖拽
    handleWheel,
    startDrag,
    onDrag,
    stopDrag,

    // 绘图
    startDraw,
    draw,
    stopDraw,

    // 撤销/重做
    undoEdit,
    redoEdit,
    clearHistory,
    saveToHistory,

    // 图片切换
    goPrevImage,
    goNextImage,

    // 未保存修改
    saveAndContinue,
    discardAndContinue,
    cancelPendingAction,

    // 操作包装（带未保存检查）
    handleSingleClean,
    canSingleClean,
    handleBatchClean,
    handleRestoreImage,
    handleStartProcess,

    // 旋转
    rotateCurrentImage,

    // 保存/还原
    saveManualEdit,
    confirmRestoreImage,
    doRestoreImage,

    // 一键修图
    startBatchClean,
    stopBatchClean,
    startBatchCleanPolling,
    stopBatchCleanPolling,
    closeBatchCleanProgress,
    startRecursiveBatchClean,
    waitForBatchCleanComplete,
    waitForProcessComplete,

    // 图片重绘
    isRedrawing,
    redrawStep,
    isBatchRedrawing,
    showBatchRedrawProgress,
    batchRedrawStatus,
    batchRedrawElapsed,
    showRedrawSettings,
    handleRedrawEnhance,
    handleRedrawWeaken,
    handleBatchRedraw,
    closeBatchRedrawProgress,

    // 生成PDF
    startProcess,
    processSingleDirectory,
    startBatchPdfProcess,
    closeBatchPdfModal,
    closeBatchPdfProgressModal,
    waitForProcessCompleteWithProgress,

    // 计时器
    formatElapsedTime,
    startProcessTimer,
    stopProcessTimer,
    startPolling,

    // 下载/预览
    downloadResult,
    previewResult,

    // 操作记录
    loadDownloadHistory,
    deleteHistoryItem,

    // 自动模式
    startBatchCleanAuto,
    startProcessAuto
  }
}
