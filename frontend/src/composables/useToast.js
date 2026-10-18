import { ref } from 'vue'

const toasts = ref([])
const errorModal = ref({ visible: false, message: '', detail: '' })
let _toastId = 0

export function useToast() {
  // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
  // 新增 persistent 可选参数：warning/info 类提示也可持久显示、点击关闭
  // （默认 false，现有调用零影响；供版本更新提示等需要用户必达的场景使用）
  function showToast(message, type = 'info', persistent = false) {
    // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    // 同消息去重：当前已有相同文字与类型的提示在显示时不再新增（错误类为持久显示，
    // 嵌入模式轮询每次失败都触发同一错误时不再逐条堆叠刷屏——刷新页面前同错只挂一条）
    const existed = toasts.value.find(t => t.message === message && t.type === type)
    if (existed) {
      return
    }
    const id = ++_toastId
    // zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
    // 增加 copied 字段：错误类提示复制成功后显示"已复制"反馈
    // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
    // persistent 存入对象：ToastContainer 据此为持久提示（如版本更新提示）渲染 × 关闭按钮
    toasts.value.push({ id, message, type, copied: false, persistent })
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    // 错误类提示不再 3 秒自动消失（错误一闪而过用户来不及看），改为持久显示、点击关闭；
    // 其余类型保持 3 秒自动消失
    if (type !== 'error' && !persistent) {
      setTimeout(() => {
        toasts.value = toasts.value.filter(t => t.id !== id)
      }, 3000)
    }
  }

  // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 关闭指定提示
  function dismissToast(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  // zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
  // 复制文本到剪贴板：execCommand 必须在用户手势的同步调用栈内执行才可靠，
  // 故同步 execCommand 路径优先（生产内网 HTTP 唯一可用），clipboard API 仅作异步兜底
  function copyText(text) {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch (e) {
      ok = false
    }
    document.body.removeChild(ta)
    if (ok) {
      return true
    }
    // 同步路径失败时尝试异步 clipboard API（安全上下文才存在），无法同步确认结果，乐观返回
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).catch(() => {})
      return true
    }
    return false
  }

  // zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
  // 点击错误提示文字：复制完整消息并短暂显示"已复制"反馈；
  // 用户正在拖选部分文字时不干预（避免全文复制覆盖用户的手动选择）；
  // 全程同步执行（不 async），保证复制动作处于点击手势上下文内；
  // 连续点击时先清旧定时器再设新，防止反馈提前消退
  const _copiedTimers = new Map()

  function copyToast(toast) {
    if (window.getSelection && String(window.getSelection())) {
      return
    }
    const ok = copyText(toast.message)
    if (!ok) {
      return
    }
    toast.copied = true
    const oldTimer = _copiedTimers.get(toast.id)
    if (oldTimer) {
      clearTimeout(oldTimer)
    }
    _copiedTimers.set(toast.id, setTimeout(() => {
      toast.copied = false
      _copiedTimers.delete(toast.id)
    }, 1800))
  }

  function showErrorModal(message, detail = '') {
    errorModal.value = { visible: true, message, detail }
  }

  function closeErrorModal() {
    errorModal.value = { visible: false, message: '', detail: '' }
  }

  return { toasts, showToast, dismissToast, copyToast, errorModal, showErrorModal, closeErrorModal }
}
