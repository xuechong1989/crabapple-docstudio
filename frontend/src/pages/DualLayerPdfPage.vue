<template>
  <div class="dual-layer-page">
    <!-- 顶部导航 -->
    <div class="itp-header">
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：左上角补系统logo图标+版本号（复用首页顶栏同款结构样式） -->
      <div class="logo-container">
        <img class="logo-icon" src="../assets/logo-white.png" alt="Logo" />
        <div class="title-text">
          <h1>转双层PDF</h1>
          <span class="version">V3.4.00</span>
        </div>
      </div>
      <div class="header-actions">
        <HeaderActions />
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：用户徽章与返回按钮互换（返回收尾最右） -->
        <UserBadge :show-logout="false" />
        <button class="itp-back-btn" @click="handleBack"><AppIcon name="arrow-left" :size="13" /> 返回首页</button>
      </div>
    </div>

    <div class="dual-layer-body">
      <!-- 左侧栏 - 文件管理区 -->
      <div class="dual-layer-sidebar">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
             文字与布局统一图片转PDF左栏：栏顶"PDF文件管理"标题头删除（图片转PDF/编辑PDF
             同款标题均已删）、上传按钮改"上传"主按钮（本模块仅文件夹上传一种入口，无下拉）、
             空状态提示文字与图片转PDF统一 -->

        <!-- 上传区域 -->
        <div class="dual-layer-upload-section">
          <label class="itp-upload-label" :class="{ disabled: isDualLayerBusy }" title="选择包含PDF文件的文件夹进行上传">
            <input
              type="file"
              ref="dualLayerFolderInput"
              webkitdirectory
              directory
              multiple
              @change="handleDualLayerFolderUpload"
              :disabled="isDualLayerBusy"
              style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:0;cursor:pointer;"
            />
            <AppIcon name="upload" /><span>上传</span>
          </label>

          <!-- 上传进度 -->
          <div v-if="dualLayerUploadProgress.visible" class="upload-progress">
            <div class="progress-info">
              <span>{{ dualLayerUploadProgress.message }}</span>
              <span>{{ dualLayerUploadProgress.current }}/{{ dualLayerUploadProgress.total }}</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: dualLayerUploadProgress.percent + '%' }"></div>
            </div>
          </div>
        </div>

        <!-- 文件夹信息卡片 -->
        <div v-if="dualLayerTaskInfo" class="task-info-card">
          <div class="task-header">
            <span class="folder-icon"><AppIcon name="folder" :size="18" /></span>
            <span class="folder-name">{{ dualLayerTaskInfo.folder_name }}</span>
          </div>
          <div class="task-stats">
            <span>共 {{ dualLayerTaskInfo.total_files }} 个PDF文件</span>
          </div>
        </div>

        <!-- 文件树 -->
        <div class="file-tree-container" v-if="dualLayerFileTree.children?.length">
          <div class="tree-header">
            <span>文件列表</span>
            <div class="tree-actions">
              <button class="icon-btn" @click="expandAllDualLayer" title="展开全部"><AppIcon name="chevrons-down" :size="14" /></button>
              <button class="icon-btn" @click="collapseAllDualLayer" title="收起全部"><AppIcon name="chevrons-up" :size="14" /></button>
            </div>
          </div>
          <div class="file-tree">
            <TreeNode
              v-for="child in dualLayerFileTree.children"
              :key="child.path"
              :node="child"
              :selected-path="dualLayerSelectedPath"
              :expanded-paths="dualLayerExpandedPaths"
              @select="handleDualLayerSelect"
              @toggle="handleDualLayerToggle"
            />
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="empty-state">
          <span class="empty-icon"><AppIcon name="folder" :size="44" /></span>
          <p>请上传文件夹开始处理</p>
        </div>
      </div>

      <!-- 中间操作区 -->
      <div class="dual-layer-main">
        <!-- 选中信息面板 -->
        <div class="dual-layer-info-panel">
          <div class="panel-header">
            <h4><AppIcon name="clipboard" /> 当前选中</h4>
          </div>
          <div class="panel-content" v-if="dualLayerSelectedNode">
            <div class="info-row">
              <span class="info-label">类型:</span>
              <span class="info-value">
                <template v-if="dualLayerSelectedNode.type === 'directory'"><AppIcon name="folder" :size="14" /> 文件夹</template>
                <template v-else><AppIcon name="file-text" :size="14" /> PDF文件</template>
              </span>
            </div>
            <div class="info-row">
              <span class="info-label">名称:</span>
              <span class="info-value">{{ dualLayerSelectedNode.name }}</span>
            </div>
            <div class="info-row" v-if="dualLayerSelectedNode.type === 'directory'">
              <span class="info-label">包含:</span>
              <span class="info-value">{{ countPdfFiles(dualLayerSelectedNode) }} 个PDF文件</span>
            </div>
            <div class="info-row" v-if="dualLayerSelectedNode.type === 'file'">
              <span class="info-label">路径:</span>
              <span class="info-value path-value">{{ dualLayerSelectedNode.path }}</span>
            </div>
            <div class="info-row" v-if="dualLayerSelectedNode.size">
              <span class="info-label">大小:</span>
              <span class="info-value">{{ formatFileSize(dualLayerSelectedNode.size) }}</span>
            </div>
          </div>
          <div class="panel-content empty" v-else>
            <p>请在左侧选择PDF文件或文件夹</p>
          </div>
        </div>

        <!-- 转换设置面板 -->
        <div class="dual-layer-settings-panel">
          <div class="panel-header">
            <h4><AppIcon name="settings" /> 转换设置</h4>
          </div>
          <div class="panel-content">
            <div class="setting-row">
              <span class="setting-label">OCR语言:</span>
              <select v-model="dualLayerOcrLang" class="setting-select">
                <option value="ch">简体中文 + 英文</option>
                <option value="en">仅英文</option>
                <option value="chinese_cht">繁体中文 + 英文</option>
                <option value="japan">日文</option>
                <option value="korean">韩文</option>
              </select>
            </div>
            <div class="setting-row checkbox-row">
              <label class="checkbox-label">
                <input type="checkbox" v-model="dualLayerKeepOriginal" />
                <span>保留原文件（转换后不删除源文件）</span>
              </label>
            </div>
            <div class="setting-row checkbox-row">
              <label class="checkbox-label">
                <input type="checkbox" v-model="dualLayerKeepStructure" />
                <span>保持目录结构（输出文件保持原目录层级）</span>
              </label>
            </div>
            <div class="setting-row checkbox-row">
              <label class="checkbox-label">
                <input type="checkbox" v-model="dualLayerAutoRotate" />
                <span>自动旋转页面（检测到90度文字时自动矫正）</span>
              </label>
            </div>
          </div>
        </div>

        <!-- 操作按钮区 -->
        <div class="dual-layer-actions">
          <button
            v-if="dualLayerSelectedNode && dualLayerSelectedNode.type === 'file' && dualLayerSelectedPdfCount === 1"
            class="btn btn-primary btn-lg"
            @click="convertDualLayerPdf"
            :disabled="!dualLayerSelectedNode || isDualLayerConverting"
            title="转换当前选中的文件或文件夹"
          >
            <AppIcon name="refresh-cw" /> 生成双层PDF
          </button>
          <button
            v-if="!dualLayerSelectedNode || dualLayerSelectedNode.type === 'directory' || dualLayerSelectedPdfCount > 1"
            class="btn btn-success btn-lg"
            @click="convertAllDualLayerPdf"
            :disabled="!dualLayerFileTree.children?.length || isDualLayerConverting"
            title="转换所有已上传的PDF文件"
          >
            <AppIcon name="package" /> 批量全部转换
          </button>

          <!-- 计时器显示 -->
          <div class="dual-layer-timer">
            <div class="timer-display" :class="{ running: dualLayerTimer.isRunning }">
              <span class="timer-icon"><AppIcon name="clock" :size="16" /></span>
              <span class="timer-value">
                {{ String(dualLayerTimer.hours).padStart(2, '0') }}时{{ String(dualLayerTimer.minutes).padStart(2, '0') }}分{{ String(dualLayerTimer.seconds).padStart(2, '0') }}秒
              </span>
            </div>
            <div v-if="dualLayerTimerSummary.visible" class="timer-summary">
              <span class="summary-label">共用时：</span>
              <span class="summary-time">{{ dualLayerTimerSummary.totalTime }}</span>
              <span class="summary-stats">
                共转换 <strong>{{ dualLayerTimerSummary.totalFiles }}</strong> 个PDF文件，
                共 <strong>{{ dualLayerTimerSummary.totalPages }}</strong> 页
              </span>
            </div>
          </div>
        </div>

        <!-- 转换进度面板 -->
        <div v-if="isDualLayerConverting" class="dual-layer-progress-panel">
          <div class="panel-header">
            <h4><AppIcon name="refresh-cw" /> 转换进度</h4>
          </div>
          <div class="panel-content">
            <div class="progress-row">
              <span class="progress-label">当前文件:</span>
              <span class="progress-value">{{ dualLayerConvertProgress.currentFile }}</span>
            </div>
            <div class="progress-row" v-if="dualLayerConvertProgress.step">
              <span class="progress-label">当前步骤:</span>
              <span class="progress-value step-value">
                {{ dualLayerConvertProgress.step }}
                <span v-if="dualLayerConvertProgress.totalPages > 0" class="page-info">
                  (第 {{ dualLayerConvertProgress.currentPage }}/{{ dualLayerConvertProgress.totalPages }} 页)
                </span>
              </span>
            </div>
            <div class="progress-row">
              <span class="progress-label">文件进度:</span>
              <div class="progress-bar-wrapper">
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: (dualLayerConvertProgress.filePercent ?? 0) + '%' }"></div>
                </div>
                <span class="progress-percent">
                  {{ dualLayerConvertProgress.filePercent === null ? '—' : dualLayerConvertProgress.filePercent + '%' }}
                </span>
              </div>
            </div>
            <div class="progress-row">
              <span class="progress-label">总体进度:</span>
              <div class="progress-bar-wrapper">
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: dualLayerConvertProgress.totalPercent + '%' }"></div>
                </div>
                <span class="progress-percent">{{ dualLayerConvertProgress.current }}/{{ dualLayerConvertProgress.total }}</span>
              </div>
            </div>
            <div class="progress-stats">
              <span class="stat-item success">已完成: {{ dualLayerConvertProgress.completed }}</span>
              <span class="stat-item processing">处理中: {{ dualLayerConvertProgress.processing }}</span>
              <span class="stat-item pending">待处理: {{ dualLayerConvertProgress.pending }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧栏 - 转换记录区 -->
      <div class="dual-layer-records">
        <div class="dual-layer-records-header">
          <h3><AppIcon name="clipboard" /> 转换记录</h3>
          <button class="btn btn-sm btn-text" @click="askDualLayerClear" title="清空所有转换记录" v-if="dualLayerHistory.length">
            <AppIcon name="trash" :size="14" /> 清空
          </button>
        </div>

        <div class="dual-layer-records-list" v-if="dualLayerHistory.length">
          <div
            class="record-card"
            v-for="(record, index) in dualLayerHistory"
            :key="index"
          >
            <div class="record-icon">
              <AppIcon v-if="record.type === 'directory'" name="folder" :size="18" />
              <AppIcon v-else name="file-text" :size="18" />
            </div>
            <div class="record-info">
              <div class="record-name" :title="record.name">{{ record.name }}</div>
              <div class="record-time" :title="record.createdAt">{{ record.createdAt }}</div>
            </div>
            <div class="record-actions">
              <button class="btn btn-sm btn-primary" @click="previewDualLayerRecord(record)" title="预览">
                <AppIcon name="eye" :size="14" />
              </button>
              <button class="btn btn-sm btn-success" @click="downloadDualLayerRecord(record)" :title="record.type === 'directory' ? '下载ZIP' : '下载'">
                <AppIcon name="download" :size="14" />
              </button>
              <button
                v-if="record.type === 'file' && record.output_files?.length"
                class="btn btn-sm btn-edit"
                @click="editDualLayerRecord(record)"
                title="编辑此PDF"
              >
                <AppIcon name="edit" :size="14" />
              </button>
            </div>
          </div>
        </div>

        <div class="empty-records" v-else>
          <span class="empty-icon"><AppIcon name="inbox" :size="44" /></span>
          <p>暂无转换记录</p>
        </div>
      </div>
    </div>

    <!-- 底部状态栏 -->
    <div class="dual-layer-footer">
      <span v-if="!isDualLayerConverting && !dualLayerConvertResult">
        <AppIcon name="info" :size="14" /> 提示: 选择左侧的PDF文件或文件夹，点击"生成双层PDF"开始转换
      </span>
      <span v-else-if="isDualLayerConverting">
        <AppIcon name="hourglass" :size="14" /> 正在转换中，请稍候...
      </span>
      <span v-else-if="dualLayerConvertResult" class="result-success">
        <AppIcon name="check-circle" :size="14" /> 转换完成! 成功: {{ dualLayerConvertResult.success }}个 | 失败: {{ dualLayerConvertResult.failed }}个 | 耗时: {{ dualLayerConvertResult.duration }}
      </span>
    </div>

    <!-- zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 -->
    <!-- 本页内联 toast 渲染已移除：与全局 ToastContainer 同源数据重复渲染（同位置叠加），统一由 RootLayout 的 ToastContainer 渲染 -->

    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：清空转换记录改统一站内确认弹框（原浏览器原生confirm） -->
    <Transition name="ds-modal">
    <div v-if="dualLayerClearConfirm" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />清空转换记录</h4>
        <p>确定要清空所有转换记录吗？清空后不可恢复。</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="dualLayerClearConfirm = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-danger" @click="confirmDualLayerClear"><AppIcon name="trash" :size="13" /> 确认清空</button>
        </div>
      </div>
    </div>
    </Transition>
  </div>
</template>

<script setup>
// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 错误翻译共享模块
import { translateError } from '../utils/translateError'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePdfStore } from '../stores/pdf'
import * as api from '../api'
import HeaderActions from '../components/HeaderActions.vue'
import UserBadge from '../components/UserBadge.vue'
import TreeNode from '../components/TreeNode.vue'
// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 本页 emoji 图标统一换单色线性 SVG 图标组件
import AppIcon from '../components/AppIcon.vue'
import { useToast } from '../composables/useToast'

const router = useRouter()
const pdfStore = usePdfStore()

// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// toasts 不再由本页渲染（内联模板已删），统一走 RootLayout 的全局 ToastContainer
const { showToast } = useToast()

// ============================================================
// 返回首页
// ============================================================
function handleBack() {
  if (isDualLayerConverting.value) {
    showToast('转换进行中，请勿离开', 'warning')
    return
  }
  router.push('/')
}

// ============================================================
// 工具函数
// ============================================================
function countPdfFiles(node) {
  if (!node) return 0
  if (node.type === 'file') {
    return node.name.toLowerCase().endsWith('.pdf') ? 1 : 0
  }
  if (node.children) {
    return node.children.reduce((sum, child) => sum + countPdfFiles(child), 0)
  }
  return 0
}

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// ============================================================
// 双层PDF状态
// ============================================================
const dualLayerFolderInput = ref(null)
const dualLayerFileTree = ref({ name: '', type: 'directory', children: [] })
const dualLayerSelectedPath = ref('')
const dualLayerExpandedPaths = ref(new Set())
const dualLayerSelectedNode = ref(null)
const dualLayerTaskInfo = ref(null)
const dualLayerTaskId = ref('')
const isDualLayerBusy = ref(false)
const isDualLayerConverting = ref(false)
const dualLayerHistory = ref([])
const dualLayerOcrLang = ref('ch')
const dualLayerKeepOriginal = ref(true)
const dualLayerKeepStructure = ref(true)
const dualLayerAutoRotate = ref(true)
const dualLayerConvertResult = ref(null)
const dualLayerUploadProgress = ref({
  visible: false,
  current: 0,
  total: 0,
  percent: 0,
  message: ''
})
const dualLayerConvertProgress = ref({
  currentFile: '',
  filePercent: null,
  currentPage: 0,
  totalPages: 0,
  step: '',
  current: 0,
  total: 0,
  totalPercent: 0,
  completed: 0,
  processing: 0,
  pending: 0
})
const dualLayerProgressTimer = ref(null)
// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 进度轮询连续失败计数
const dualLayerPollFailCount = ref(0)

// 双层PDF转换计时器
const dualLayerTimer = ref({
  hours: 0,
  minutes: 0,
  seconds: 0,
  intervalId: null,
  startTime: null,
  isRunning: false
})
const dualLayerTimerSummary = ref({
  visible: false,
  totalTime: '',
  totalFiles: 0,
  totalPages: 0
})

const dualLayerSelectedPdfCount = computed(() => {
  const node = dualLayerSelectedNode.value
  if (!node) return 0
  if (node.type === 'file') {
    return node.name?.toLowerCase().endsWith('.pdf') ? 1 : 0
  }
  return countPdfFiles(node)
})

// ============================================================
// 文件树操作
// ============================================================
function handleDualLayerSelect(node) {
  dualLayerSelectedPath.value = node.path
  dualLayerSelectedNode.value = node
}

function handleDualLayerToggle(path) {
  if (dualLayerExpandedPaths.value.has(path)) {
    dualLayerExpandedPaths.value.delete(path)
  } else {
    dualLayerExpandedPaths.value.add(path)
  }
  dualLayerExpandedPaths.value = new Set(dualLayerExpandedPaths.value)
}

function expandAllDualLayer() {
  const expandAll = (node) => {
    if (node.type === 'directory') {
      dualLayerExpandedPaths.value.add(node.path)
      if (node.children) {
        node.children.forEach(expandAll)
      }
    }
  }
  if (dualLayerFileTree.value.children) {
    dualLayerFileTree.value.children.forEach(expandAll)
  }
  dualLayerExpandedPaths.value = new Set(dualLayerExpandedPaths.value)
}

function collapseAllDualLayer() {
  dualLayerExpandedPaths.value = new Set()
}

// ============================================================
// 上传
// ============================================================
async function handleDualLayerFolderUpload(event) {
  const files = event.target.files
  if (!files || files.length === 0) return

  const pdfFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'))

  if (pdfFiles.length === 0) {
    showToast('所选文件夹中没有PDF文件', 'warning')
    event.target.value = ''
    return
  }

  isDualLayerBusy.value = true
  dualLayerUploadProgress.value = {
    visible: true,
    current: 0,
    total: pdfFiles.length,
    percent: 0,
    message: '正在上传...'
  }

  try {
    const formData = new FormData()
    pdfFiles.forEach(file => {
      formData.append('files', file, file.webkitRelativePath || file.name)
    })

    const response = await api.dualLayerUpload(formData)

    const result = response.data

    dualLayerTaskId.value = result.task_id || ''
    dualLayerFileTree.value = result.file_tree || { name: '', type: 'directory', children: [] }
    dualLayerTaskInfo.value = {
      folder_name: result.folder_name,
      total_files: result.total_files
    }

    // 自动展开第一层
    if (dualLayerFileTree.value.children) {
      dualLayerFileTree.value.children.forEach(child => {
        if (child.type === 'directory') {
          dualLayerExpandedPaths.value.add(child.path)
        }
      })
    }

    showToast(`成功上传 ${result.total_files} 个PDF文件`, 'success')
  } catch (err) {
    showToast(translateError(err, '上传失败: '), 'error')
  } finally {
    isDualLayerBusy.value = false
    dualLayerUploadProgress.value.visible = false
    event.target.value = ''
  }
}

// ============================================================
// 转换
// ============================================================
async function convertDualLayerPdf() {
  if (!dualLayerSelectedNode.value) {
    showToast('请先选择要转换的PDF文件或文件夹', 'warning')
    return
  }

  const totalCount = dualLayerSelectedPdfCount.value
  isDualLayerConverting.value = true
  dualLayerConvertResult.value = null
  dualLayerConvertProgress.value = {
    currentFile: '',
    filePercent: null,
    currentPage: 0,
    totalPages: 0,
    step: '',
    current: 0,
    total: totalCount,
    totalPercent: 0,
    completed: 0,
    processing: totalCount > 0 ? 1 : 0,
    pending: Math.max(0, totalCount - 1)
  }

  startDualLayerTimer()
  startDualLayerProgressPolling({ path: dualLayerSelectedNode.value.path })

  const startTime = Date.now()
  let totalPagesProcessed = 0

  try {
    const response = await api.dualLayerConvert({
      path: dualLayerSelectedNode.value.path,
      type: dualLayerSelectedNode.value.type,
      ocr_lang: dualLayerOcrLang.value,
      keep_original: dualLayerKeepOriginal.value,
      keep_structure: dualLayerKeepStructure.value,
      auto_rotate: dualLayerAutoRotate.value
    })

    const result = response.data

    const duration = Math.round((Date.now() - startTime) / 1000)
    const durationStr = duration >= 60 ? `${Math.floor(duration / 60)}分${duration % 60}秒` : `${duration}秒`

    dualLayerConvertResult.value = {
      success: result.success_count || 0,
      failed: result.failed_count || 0,
      duration: durationStr
    }

    const finalTotal = dualLayerConvertProgress.value.total || totalCount
    const doneCount = (result.success_count || 0) + (result.failed_count || 0)
    const finalCompleted = Math.min(doneCount, finalTotal)
    dualLayerConvertProgress.value = {
      currentFile: dualLayerConvertProgress.value.currentFile,
      filePercent: finalTotal > 0 ? 100 : null,
      current: finalCompleted,
      total: finalTotal,
      totalPercent: finalTotal > 0 ? 100 : 0,
      completed: finalCompleted,
      processing: 0,
      pending: Math.max(0, finalTotal - finalCompleted)
    }

    const records = result.records || (result.record ? [result.record] : [])
    addDualLayerHistoryRecords(records)

    totalPagesProcessed = result.total_pages || dualLayerConvertProgress.value.totalPages || 0

    showToast(`转换完成！成功: ${result.success_count} 个`, 'success')
  } catch (err) {
    showToast(translateError(err, '转换失败: '), 'error')
    dualLayerConvertResult.value = null
  } finally {
    stopDualLayerProgressPolling()
    isDualLayerConverting.value = false

    const successCount = dualLayerConvertResult.value?.success || 0
    stopDualLayerTimer(successCount, totalPagesProcessed)
  }
}

async function convertAllDualLayerPdf() {
  if (!dualLayerFileTree.value.children?.length) {
    showToast('请先上传PDF文件', 'warning')
    return
  }

  const totalCount = countPdfFiles(dualLayerFileTree.value)
  isDualLayerConverting.value = true
  dualLayerConvertResult.value = null
  dualLayerConvertProgress.value = {
    currentFile: '',
    filePercent: null,
    currentPage: 0,
    totalPages: 0,
    step: '',
    current: 0,
    total: totalCount,
    totalPercent: 0,
    completed: 0,
    processing: totalCount > 0 ? 1 : 0,
    pending: Math.max(0, totalCount - 1)
  }

  startDualLayerTimer()
  startDualLayerProgressPolling({ taskId: dualLayerTaskId.value })

  const startTime = Date.now()
  let totalPagesProcessed = 0

  try {
    const response = await api.dualLayerConvertAll({
      task_id: dualLayerTaskId.value,
      ocr_lang: dualLayerOcrLang.value,
      keep_original: dualLayerKeepOriginal.value,
      keep_structure: dualLayerKeepStructure.value,
      auto_rotate: dualLayerAutoRotate.value
    })

    const result = response.data

    const duration = Math.round((Date.now() - startTime) / 1000)
    const durationStr = duration >= 60 ? `${Math.floor(duration / 60)}分${duration % 60}秒` : `${duration}秒`

    dualLayerConvertResult.value = {
      success: result.success_count || 0,
      failed: result.failed_count || 0,
      duration: durationStr
    }

    const finalTotal = dualLayerConvertProgress.value.total || totalCount
    const doneCount = (result.success_count || 0) + (result.failed_count || 0)
    const finalCompleted = Math.min(doneCount, finalTotal)
    dualLayerConvertProgress.value = {
      currentFile: dualLayerConvertProgress.value.currentFile,
      filePercent: finalTotal > 0 ? 100 : null,
      current: finalCompleted,
      total: finalTotal,
      totalPercent: finalTotal > 0 ? 100 : 0,
      completed: finalCompleted,
      processing: 0,
      pending: Math.max(0, finalTotal - finalCompleted)
    }

    if (result.records?.length) {
      addDualLayerHistoryRecords(result.records)
    } else {
      await refreshDualLayerHistory()
    }

    totalPagesProcessed = result.total_pages || dualLayerConvertProgress.value.totalPages || 0

    showToast(`批量转换完成！成功: ${result.success_count} 个`, 'success')
  } catch (err) {
    showToast(translateError(err, '批量转换失败: '), 'error')
    dualLayerConvertResult.value = null
  } finally {
    stopDualLayerProgressPolling()
    isDualLayerConverting.value = false

    const successCount = dualLayerConvertResult.value?.success || 0
    stopDualLayerTimer(successCount, totalPagesProcessed)
  }
}

// ============================================================
// 进度轮询
// ============================================================
function startDualLayerProgressPolling({ path, taskId }) {
  stopDualLayerProgressPolling()
  if (!path && !taskId) return
  // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 每次启动轮询重置失败计数
  dualLayerPollFailCount.value = 0
  dualLayerProgressTimer.value = setInterval(async () => {
    try {
      const params = {}
      if (path) params.path = path
      if (taskId) params.task_id = taskId
      const response = await api.dualLayerGetProgress(params)
      // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 成功即重置失败计数
      dualLayerPollFailCount.value = 0
      const result = response.data
      if (!result || !result.progress) return
      const progress = result.progress
      dualLayerConvertProgress.value = {
        currentFile: progress.currentFile || '',
        filePercent: progress.filePercent ?? null,
        currentPage: progress.currentPage || 0,
        totalPages: progress.totalPages || 0,
        step: progress.step || '',
        current: progress.current || 0,
        total: progress.total || 0,
        totalPercent: progress.totalPercent || 0,
        completed: progress.completed || 0,
        processing: progress.processing || 0,
        pending: progress.pending || 0
      }
    } catch (err) {
      // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
      // 连续失败计数：超过上限判定进度通道失联，停止轮询并明确提示（原实现仅 console，
      // 进度条会永久停滞且用户无感知）
      dualLayerPollFailCount.value = (dualLayerPollFailCount.value || 0) + 1
      console.error('[双层PDF] 进度获取失败(' + dualLayerPollFailCount.value + '/20):', err.message || err)
      if (dualLayerPollFailCount.value >= 20) {
        stopDualLayerProgressPolling()
        showToast('进度获取连续失败已停止刷新——转换可能仍在后台进行，稍后请在历史记录中查看结果；若服务已停止请重启后重试', 'error')
      }
    }
  }, 500)
}

function stopDualLayerProgressPolling() {
  if (dualLayerProgressTimer.value) {
    clearInterval(dualLayerProgressTimer.value)
    dualLayerProgressTimer.value = null
  }
}

// ============================================================
// 计时器
// ============================================================
function startDualLayerTimer() {
  dualLayerTimer.value.hours = 0
  dualLayerTimer.value.minutes = 0
  dualLayerTimer.value.seconds = 0
  dualLayerTimer.value.startTime = Date.now()
  dualLayerTimer.value.isRunning = true
  dualLayerTimerSummary.value.visible = false

  if (dualLayerTimer.value.intervalId) {
    clearInterval(dualLayerTimer.value.intervalId)
  }

  dualLayerTimer.value.intervalId = setInterval(() => {
    const elapsed = Math.floor((Date.now() - dualLayerTimer.value.startTime) / 1000)
    dualLayerTimer.value.hours = Math.floor(elapsed / 3600)
    dualLayerTimer.value.minutes = Math.floor((elapsed % 3600) / 60)
    dualLayerTimer.value.seconds = elapsed % 60
  }, 1000)
}

function stopDualLayerTimer(totalFiles, totalPages) {
  if (dualLayerTimer.value.intervalId) {
    clearInterval(dualLayerTimer.value.intervalId)
    dualLayerTimer.value.intervalId = null
  }
  dualLayerTimer.value.isRunning = false

  const h = dualLayerTimer.value.hours
  const m = dualLayerTimer.value.minutes
  const s = dualLayerTimer.value.seconds

  let timeStr = ''
  if (h > 0) {
    timeStr = `${String(h).padStart(2, '0')}时${String(m).padStart(2, '0')}分${String(s).padStart(2, '0')}秒`
  } else if (m > 0) {
    timeStr = `${String(m).padStart(2, '0')}分${String(s).padStart(2, '0')}秒`
  } else {
    timeStr = `${s}秒`
  }

  dualLayerTimerSummary.value = {
    visible: true,
    totalTime: timeStr,
    totalFiles: totalFiles || 0,
    totalPages: totalPages || 0
  }
}

function resetDualLayerTimer() {
  if (dualLayerTimer.value.intervalId) {
    clearInterval(dualLayerTimer.value.intervalId)
    dualLayerTimer.value.intervalId = null
  }
  dualLayerTimer.value.hours = 0
  dualLayerTimer.value.minutes = 0
  dualLayerTimer.value.seconds = 0
  dualLayerTimer.value.startTime = null
  dualLayerTimer.value.isRunning = false
  dualLayerTimerSummary.value.visible = false
}

// ============================================================
// 转换记录
// ============================================================
async function refreshDualLayerHistory() {
  try {
    const response = await api.dualLayerGetHistory()
    const result = response.data
    dualLayerHistory.value = result.history || []
  } catch (err) {
    console.error('[双层PDF] 历史记录加载失败:', err.message || err)
  }
}

function addDualLayerHistoryRecords(records) {
  if (!records || records.length === 0) return
  const existingIds = new Set(dualLayerHistory.value.map(record => record.id))
  const newRecords = records.filter(record => record?.id && !existingIds.has(record.id))
  if (newRecords.length > 0) {
    dualLayerHistory.value = [...newRecords, ...dualLayerHistory.value]
  }
}

// xuechong 2026-10-10 研发BUG-0071 用户复验：清空转换记录改统一站内确认弹框（原浏览器原生confirm）
const dualLayerClearConfirm = ref(false)

function askDualLayerClear() {
  dualLayerClearConfirm.value = true
}

async function confirmDualLayerClear() {
  dualLayerClearConfirm.value = false
  try {
    await api.dualLayerClearHistory()
    dualLayerHistory.value = []
    showToast('转换记录已清空', 'success')
  } catch (err) {
    showToast('清空失败', 'error')
  }
}

function previewDualLayerRecord(record) {
  const previewUrl = `/api/dual-layer/preview/${record.id}`
  window.open(previewUrl, '_blank')
}

function editDualLayerRecord(record) {
  if (!record.output_files?.length) {
    showToast('没有可编辑的PDF文件', 'warning')
    return
  }
  pdfStore.setPendingEdit({
    source: 'dual-layer-pdf',
    pdfPath: record.output_files[0],
    fileName: record.name
  })
  router.push('/edit-pdf')
}

async function downloadDualLayerRecord(record) {
  const downloadUrl = `/api/dual-layer/download/${record.id}`

  try {
    const response = await fetch(downloadUrl)

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      showToast(errorData.detail || '下载失败', 'error')
      return
    }

    let filename = record.type === 'directory' ? `${record.name}.zip` : record.name
    const contentDisposition = response.headers.get('Content-Disposition')
    if (contentDisposition) {
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/i)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      }
    }

    const blob = await response.blob()
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
    showToast(translateError(err, '下载失败: '), 'error')
  }
}

// ============================================================
// 清理
// ============================================================
onMounted(() => {
  refreshDualLayerHistory()
})

onUnmounted(() => {
  stopDualLayerProgressPolling()
  resetDualLayerTimer()
})
</script>

<style scoped>
.dual-layer-page {
  width: 100vw;
  max-width: 100vw;
  height: 100vh;
  max-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  overflow: hidden;
}
</style>
