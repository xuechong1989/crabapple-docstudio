import axios from 'axios'

// 基础API配置 - 超时1小时（3600秒）
const api = axios.create({
  baseURL: '/api',
  timeout: 3600000  // 1小时超时（3600秒）
})

// xuechong 2026-06-01 请求拦截器 — 自动附加 JWT token
api.interceptors.request.use((config) => {
  try {
    // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    // 嵌入模式（form-in页签iframe）请求统一附加X-Embed-Mode头：后端按嵌入管理员直通放行，
    // token过期或页面残留旧登录态时接口不再401"未登录"（嵌入口径=免登录管理员最高权限）
    if (sessionStorage.getItem('ds_embed_mode') === '1') {
      config.headers['X-Embed-Mode'] = '1'
    }
    const saved = localStorage.getItem('ds_auth')
    if (saved) {
      const data = JSON.parse(saved)
      if (data.token) {
        config.headers.Authorization = 'Bearer ' + data.token
      }
    }
  } catch (e) {
    // 忽略
  }
  return config
}, (error) => Promise.reject(error))

// V3.1.01 xuechong 2026-07-25 响应拦截器 — 401 时自动刷新 token，失败则清除登录并跳转
let _isRefreshing = false
let _refreshPromise = null
let _getAuthStore = null

// V3.1.01 xuechong 2026-07-25 注册 auth store 获取函数（避免循环依赖）
export function registerAuthStoreGetter(fn) { _getAuthStore = fn }

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      // 排除登录和刷新请求本身（兼容 baseURL 带不带前缀）
      const reqUrl = originalRequest.url || ''
      if (reqUrl.includes('/auth/login') || reqUrl.includes('/auth/refresh') || reqUrl.includes('/auth/verify')) {
        return Promise.reject(error)
      }
      originalRequest._retry = true

      if (!_isRefreshing) {
        _isRefreshing = true
        _refreshPromise = api.post('/auth/refresh').then(res => {
          if (res.data.success && res.data.token) {
            const saved = JSON.parse(localStorage.getItem('ds_auth') || '{}')
            saved.token = res.data.token
            localStorage.setItem('ds_auth', JSON.stringify(saved))
            return res.data.token
          }
          throw new Error('refresh failed')
        }).catch(() => {
          // V3.1.01 xuechong 2026-07-25 刷新失败时清除登录状态并跳转登录页
          try { localStorage.removeItem('ds_auth') } catch (e) { /* */ }
          try {
            if (_getAuthStore) {
              const authStore = _getAuthStore()
              authStore.logout()
            }
          } catch (e) { /* store 未初始化时忽略 */ }
          // xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
          // 刷新失败说明登录态已彻底失效：整页跳转登录页并带过期原因，让用户立刻看到
          // "登录已过期"提示并重新登录，不再留在页面里继续操作然后处处静默失败；
          // 已在登录页时不再重复跳转（避免与路由守卫进门核验的跳转竞争，两者指向同一地址）
          if (!window.location.pathname.startsWith('/login')) {
            window.location.href = '/login?reason=expired'
          }
          return null
        }).finally(() => {
          _isRefreshing = false
          _refreshPromise = null
        })
      }

      return _refreshPromise.then(token => {
        if (token) {
          originalRequest.headers.Authorization = 'Bearer ' + token
          return api(originalRequest)
        }
        return Promise.reject(error)
      })
    }
    return Promise.reject(error)
  }
)

// ============================================================
// 文件夹上传相关 API
// ============================================================

// xuechong 2026-06-01 上传文件夹（支持 AbortController 取消上传）
// xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 支持追加模式（分批上传复用同一任务）
export const uploadFolder = (formData, onUploadProgress, signal, taskId) => api.post(
  taskId ? `/upload-folder?task_id=${encodeURIComponent(taskId)}` : '/upload-folder',
  formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
  timeout: 3600000,  // 上传超时1小时
  onUploadProgress,
  signal  // xuechong 2026-06-01 支持 AbortController 取消上传请求
})

// zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
// 上传失败诊断包上报（后端免鉴权端点）：fire-and-forget，失败静默——诊断本身不得产生新报错
export const reportUploadDiagnostic = (payload) => api.post('/upload-diagnostic', payload, { timeout: 10000 }).catch(() => {})

// 获取上传任务状态
export const getUploadTask = (taskId) => api.get(`/upload-task/${taskId}`)

// 获取上传文件树
export const getUploadFileTree = (taskId) => api.get(`/upload-file-tree/${taskId}`)

// 处理上传的文件夹（只处理指定目录）
export const processUpload = (taskId, addPageNumber = true, selectedPath = '') => {
  const params = new URLSearchParams({
    add_page_number: addPageNumber,
    selected_path: selectedPath
  })
  return api.post(`/process-upload/${taskId}?${params.toString()}`)
}

// 删除上传任务中的单个文件或文件夹
export const deleteUploadFile = (taskId, filePath) =>
  api.delete(`/upload-task/${taskId}/file`, { params: { file_path: filePath } })

// xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 嵌入模式（form-in页签iframe，地址带embed=1进来）下浏览器直链请求（预览新窗口/img src/下载）
// 带不上cookie（iframe跨域第三方上下文种cookie被浏览器拦）与Authorization头，
// 统一在URL上拼token参数，后端鉴权中间件按 cookie>header>query 顺序取token并走完整校验；
// 普通直连模式（sessionStorage无ds_embed_mode标记）不拼token，cookie鉴权行为完全不变，两模式互不影响
// xuechong 2026-09-30 同需求追加：直链同时拼embed=1（后端嵌入直通参数），token过期时直链也不再401
export function withEmbedToken(url) {
  try {
    if (sessionStorage.getItem('ds_embed_mode') !== '1') return url
    let query = 'embed=1'
    const saved = localStorage.getItem('ds_auth')
    if (saved) {
      const parsed = JSON.parse(saved)
      const token = parsed && parsed.token
      if (token) { query = query + '&token=' + encodeURIComponent(token) }
    }
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + query
  } catch (e) {
    return url
  }
}

// 获取预览URL（原图）
export const getPreviewUrl = (taskId, path) =>
  withEmbedToken(`/api/preview-upload/${taskId}?path=${encodeURIComponent(path)}`)

// xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 修图备份（原图区）预览URL：与上方两个预览URL同款走withEmbedToken——此前useImageToPdf里
// 9处裸拼/api/preview-backup直链，嵌入模式下img请求带不上嵌入头与embed参数，401导致原图区空白
export const getBackupPreviewUrl = (taskId, path) =>
  withEmbedToken(`/api/preview-backup/${taskId}?path=${encodeURIComponent(path)}`)

// 获取净化后图片预览URL
export const getCleanedPreviewUrl = (taskId, path) =>
  withEmbedToken(`/api/preview-cleaned/${taskId}?path=${encodeURIComponent(path)}`)

// 获取下载URL
export const getDownloadUrl = (taskId) => withEmbedToken(`/api/download-result/${taskId}`)

// 获取预览PDF的URL（在浏览器中打开）
export const getPreviewPdfUrl = (taskId) => withEmbedToken(`/api/preview-pdf/${taskId}`)

// 获取下载历史列表（添加时间戳避免缓存）
export const getDownloadHistory = () => api.get(`/download-history?_t=${Date.now()}`)

// 获取下载历史项的下载URL（根据索引）
export const getDownloadHistoryItemUrl = (index) => withEmbedToken(`/api/download-history-item/${index}`)

// 获取下载历史项的预览URL（根据索引）
export const getPreviewHistoryItemUrl = (index) => withEmbedToken(`/api/preview-history-item/${index}`)

// 获取删除历史项的URL（根据索引）
export const getDeleteHistoryItemUrl = (index) => withEmbedToken(`/api/download-history-item/${index}`)

// 下载处理结果（blob，用于浏览器下载）
export const downloadResultBlob = (taskId) =>
  api.get(`/download-result/${taskId}`, { responseType: 'blob' })

// 删除操作记录项
export const deleteDownloadHistoryItem = (index) => api.delete(`/download-history-item/${index}`)

// 标记历史项为已编辑
export const markHistoryEdited = (index) => api.put(`/download-history-item/${index}/mark-edited`)

// 标记历史项为编辑后下载
export const markHistoryEditDownloaded = (index) => api.put(`/download-history-item/${index}/edit-downloaded`)

// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 重命名转换记录（只改记录显示名，下载文件名随之变化，物理PDF不动；
// 接口为研发需求-0164既有接口，本次图档前端首次接入调用，new_name走query参数）
export const renameDownloadHistoryItem = (index, newName) =>
  api.put(`/download-history-item/${index}/rename`, null, { params: { new_name: newName } })

// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 转换记录批量下载URL（按索引列表打一个ZIP，逗号分隔；嵌入模式同样走withEmbedToken带token直链）
export const getDownloadHistoryBatchUrl = (indices) =>
  withEmbedToken(`/api/download-history-item-batch?indices=${indices.join(',')}`)

// ============================================================
// 图片修图相关 API
// ============================================================

// 一键修图（批量净化所选目录下所有图片）
export const batchClean = (taskId, selectedPath = '') => {
  const params = new URLSearchParams({ selected_path: selectedPath })
  return api.post(`/batch-clean/${taskId}?${params.toString()}`)
}

// 获取一键修图任务状态
export const getBatchCleanStatus = (taskId) => api.get(`/batch-clean-status/${taskId}`)

// xuechong 2026-06-01 上传历史记录 API
export const getUploadHistory = () => api.get('/upload-history')
export const deleteUploadHistoryItem = (taskId) => api.delete(`/upload-history/${taskId}`)
export const clearUploadHistory = () => api.delete('/upload-history')

// xuechong 2026-06-01 获取当前所有活跃的上传任务（用于前端状态恢复）
export const getActiveTasks = () => api.get('/active-tasks')

// 取消任务（支持批量修图等）
export const cancelTask = (taskId) => api.post(`/task/${taskId}/cancel`)

// 保存手动修图结果（使用JSON传输，支持大图片）
export const saveManualEdit = (taskId, path, imageData) => {
  return api.post(`/save-manual-edit/${taskId}?path=${encodeURIComponent(path)}`, {
    image_data: imageData
  }, {
    headers: { 'Content-Type': 'application/json' },
    maxContentLength: 100 * 1024 * 1024,  // 100MB
    maxBodyLength: 100 * 1024 * 1024
  })
}

// 还原图片为原图
export const restoreImage = (taskId, path) => 
  api.post(`/restore-image/${taskId}?path=${encodeURIComponent(path)}`)

// 旋转图片（left=逆时针90度, right=顺时针90度）
export const rotateImage = (taskId, path, direction = 'right') =>
  api.post(`/rotate-image/${taskId}?path=${encodeURIComponent(path)}&direction=${direction}`)

// 图片重绘（direction: enhance=加深, weaken=变浅; step: 调整幅度）
export const redrawImage = (taskId, path, direction = 'enhance', step = 10) =>
  api.post(`/redraw-image/${taskId}?path=${encodeURIComponent(path)}&direction=${direction}&step=${step}`)

// 批量重绘
export const batchRedraw = (taskId, selectedPath, direction = 'enhance', step = 10) => {
  const params = new URLSearchParams({ selected_path: selectedPath, direction, step })
  return api.post(`/batch-redraw/${taskId}?${params.toString()}`)
}

// 批量重绘状态
export const getBatchRedrawStatus = (taskId) => api.get(`/batch-redraw-status/${taskId}`)

// 检查图片是否有备份
export const checkBackup = (taskId, path) => 
  api.get(`/check-backup/${taskId}?path=${encodeURIComponent(path)}`)

// 删除上传任务
export const deleteUploadTask = (taskId) => api.delete(`/upload-task/${taskId}`)

// ============================================================
// 目录相关（保留兼容）
// ============================================================
export const getDirectoryTree = () => api.get('/directory-tree')
export const getDirectoryInfo = () => api.get('/directory-info')
export const browseDirs = (path = '') => api.get('/browse-dirs', { params: { path } })
export const setSourceDir = (path) => api.post('/config/source-dir', { path })
export const setTargetDir = (path) => api.post('/config/target-dir', { path })

// ============================================================
// 文件相关（保留兼容）
// ============================================================
export const previewFile = (path) => withEmbedToken(`/api/file/preview?path=${encodeURIComponent(path)}`)
export const cleanFile = (sourcePath, taskId) => api.post('/file/clean', { source_path: sourcePath, task_id: taskId, save_to_source: true })
export const saveEditedImage = (sourcePath, imageData) => api.post('/file/save-edited', { source_path: sourcePath, image_data: imageData })

// ============================================================
// 批量任务（保留兼容）
// ============================================================
export const batchConvert = (folderPath, outputFormat = 'pdf', addPageNumber = true) => 
  api.post('/batch/convert', { folder_path: folderPath, output_format: outputFormat, add_page_number: addPageNumber })
export const getBatchStatus = (taskId) => api.get(`/batch/status/${taskId}`)
export const stopBatchTask = (taskId) => api.post(`/batch/stop/${taskId}`)

// ============================================================
// 系统
// ============================================================
export const getSystemStatus = () => api.get('/admin/status')
export const getLogs = (count = 100) => api.get('/logs', { params: { count } })

// 心跳检测（适当超时，避免繁忙时误判）
export const heartbeat = () => api.get('/health', { timeout: 5000 })

// ============================================================
// 编辑PDF操作记录
// ============================================================
export const getEditPdfHistory = () => api.get(`/edit-pdf/history?_t=${Date.now()}`)

// zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 操作记录三操作改为按记录键 task_id+file_id 寻址（原下标寻址在"取列表后、点击前"
// 发生记录插入时全体下标错位，会预览/下载/删除到别的文件）；预览/下载URL携带 _t
// 缓存戳防浏览器回放旧响应
export const deleteEditPdfHistory = (taskId, fileId) =>
  api.delete(`/edit-pdf/record/${taskId}/${fileId}`)

export const getEditPdfHistoryPreviewUrl = (taskId, fileId) =>
  withEmbedToken(`/api/edit-pdf/record/${taskId}/${fileId}/preview?_t=${Date.now()}`)
export const getEditPdfHistoryDownloadUrl = (index) => withEmbedToken(`/api/edit-pdf/history-download/${index}`)

// 编辑PDF - 上传多个PDF文件
export const uploadEditPdfMultiple = (formData) => api.post('/edit-pdf/upload-multiple', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
  timeout: 3600000
})

// 编辑PDF - 获取PDF文件页面列表
export const getEditPdfFilePages = (taskId, fileId) =>
  api.get(`/edit-pdf/file/${taskId}/${fileId}/pages`)

// 编辑PDF - 保存编辑后的页面
export const saveEditPdfPage = (data) => api.post('/edit-pdf/save-page', data)

// zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 编辑PDF - 还原页面
// （撤销该页已保存的手工编辑：修图过的页回到修图后状态，未修图页回到原始页）
export const restoreEditPdfPage = (data) => api.post('/edit-pdf/restore-page', data)

// 编辑PDF - 一键处理（原"一键修图"演进：可选AI清洁+OCR，并设置处理配方长期生效）
export const cleanAllEditPdfPages = (data) => api.post('/edit-pdf/clean-all-pages', data)

// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 编辑PDF - 查询文件当前处理配方（一键处理配置弹窗回显用）
export const getEditPdfProcessRecipe = (taskId, fileId) =>
  api.get(`/edit-pdf/recipe/${taskId}/${fileId}`)

// 编辑PDF - 获取清洁进度
export const getCleanAllProgress = (taskId, fileId) =>
  api.get(`/edit-pdf/clean-all-progress/${taskId}/${fileId}`)

// 编辑PDF - 检查未保存的修改
export const checkEditPdfUnsaved = (taskId, fileId) =>
  api.get(`/edit-pdf/check-unsaved/${taskId}/${fileId}`)

// 编辑PDF - 导入PDF（从转换记录恢复编辑会话）
export const importEditPdf = (data) => api.post('/edit-pdf/import', data)

// 编辑PDF - 下载操作记录中的PDF（返回blob，按键寻址+缓存戳）
export const downloadEditPdfHistoryBlob = (taskId, fileId) =>
  api.get(`/edit-pdf/record/${taskId}/${fileId}/download?_t=${Date.now()}`, { responseType: 'blob' })

// 编辑PDF - 获取编辑后的页面图片URL
export const getEditPdfPageEditedUrl = (taskId, fileId, pageNum) =>
  withEmbedToken(`/api/edit-pdf/page/${taskId}/${fileId}/${pageNum}/edited`)

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 编辑PDF - 批量下载URL构造（勾选≥2个PDF时一次下载ZIP；处理选项由各文件配方决定，
// 下载不再携带开关参数；window.open 同站携带 cookie 鉴权，与单文件下载同模式）
export const getEditPdfBatchDownloadUrl = (taskId, fileIds) => {
  const params = new URLSearchParams()
  params.set('file_ids', fileIds.join(','))
  return withEmbedToken(`/api/edit-pdf/download-multiple/${taskId}?${params.toString()}`)
}

// ============================================================
// 编辑PDF一键OCR
// ============================================================
export const ocrAllPages = (taskId, fileId, ocrLang = 'ch') =>
  api.post(`/edit-pdf/ocr-all-pages`, { task_id: taskId, file_id: fileId, ocr_lang: ocrLang })

export const getOcrAllProgress = (taskId, fileId) =>
  api.get(`/edit-pdf/ocr-all-progress/${taskId}/${fileId}`)

// ============================================================
// 双层PDF
// ============================================================
export const dualLayerUpload = (formData) =>
  api.post('/dual-layer/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const dualLayerConvert = (data) =>
  api.post('/dual-layer/convert', data)

export const dualLayerConvertAll = (data) =>
  api.post('/dual-layer/convert-all', data)

export const dualLayerGetProgress = (params) =>
  api.get('/dual-layer/progress', { params })

export const dualLayerGetHistory = () =>
  api.get('/dual-layer/history')

export const dualLayerClearHistory = () =>
  api.delete('/dual-layer/history')

export const dualLayerGetDownloadUrl = (recordId) =>
  withEmbedToken(`/api/dual-layer/download/${recordId}`)

// ============================================================
// 登录验证
// ============================================================
export const verifyLogin = (hashedPassword) => api.post('/auth/verify', { password: hashedPassword })

// xuechong 2026-06-01 新版用户认证 API
export const userLogin = (username, password) => api.post('/auth/login', { username, password })
export const userRegister = (username, password, displayName, role) => api.post('/auth/register', { username, password, display_name: displayName, role: role || 'user' })
export const getCurrentUser = () => api.get('/auth/me')
// xuechong 2026-06-02 管理员用户管理 API
export const resetUserPassword = (username, newPassword) => api.post(`/auth/users/${username}/reset-password`, newPassword ? { new_password: newPassword } : {})

export default api
