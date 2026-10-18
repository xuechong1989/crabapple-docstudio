// xuechong 2026-10-10 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 全局弹窗标题栏拖拽（用户复验要求）：按住任意弹窗标题栏拖动即可移动弹窗位置。
// 实现：document 级 mousedown 事件委托——命中已知弹窗标题栏（且目标不是按钮/输入框）时，
// 拖拽最近的弹窗容器（transform 平移，累计偏移存 dataset；弹窗关闭重开自动复位居中）。
// 打开/关闭渐变动画期间的 transform 由 animation 优先渲染，与拖拽偏移互不冲突。

const HEADER_SEL = '.itp-history-header, .modal-header, .utm-header, .upload-modal-header, .error-modal-header, .auto-confirm-title, .login-header'
const DIALOG_SEL = '.itp-history-dialog, .itp-unsaved-dialog, .itp-delete-dialog, .itp-restore-dialog, .itp-batch-pdf-dialog, .itp-batch-progress-dialog, .itp-redraw-settings-dialog, .auto-confirm-dialog, .utm-modal, .upload-modal-dialog, .modal-content, .error-modal, .login-modal'
const INTERACTIVE_SEL = 'button, input, select, textarea, a, [contenteditable]'

export function setupDialogDrag() {
  document.addEventListener('mousedown', (e) => {
    // 标题栏上的按钮（关闭等）/输入控件不触发拖拽
    if (e.target.closest(INTERACTIVE_SEL)) return
    if (e.button !== 0) return

    const dialog = e.target.closest(DIALOG_SEL)
    if (!dialog) return

    // 标题栏：结构化头部 或 弹窗直接子级标题（六类确认框的 h4 等）
    let header = e.target.closest(HEADER_SEL)
    if (!header) {
      const scopeTitle = dialog.querySelector(':scope > h4, :scope > h2')
      if (scopeTitle && (scopeTitle === e.target || scopeTitle.contains(e.target))) {
        header = scopeTitle
      }
    }
    if (!header || !(header === e.target || header.contains(e.target))) return

    e.preventDefault()
    const startX = e.clientX
    const startY = e.clientY
    const originX = parseFloat(dialog.dataset.dragX || '0')
    const originY = parseFloat(dialog.dataset.dragY || '0')
    document.body.style.userSelect = 'none'

    const onMove = (ev) => {
      const nx = originX + ev.clientX - startX
      const ny = originY + ev.clientY - startY
      dialog.dataset.dragX = String(nx)
      dialog.dataset.dragY = String(ny)
      dialog.style.transform = `translate(${nx}px, ${ny}px)`
    }
    const onUp = () => {
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  })
}
