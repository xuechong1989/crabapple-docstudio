// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
// 全局错误翻译工具：把 axios/浏览器英文原始错误翻译成人话（含原因与恢复方式）。
// 逻辑与 useImageToPdf.js 的 classifyUploadError 同源，供 EditPdfPage/DualLayerPdfPage 复用，
// 消除各页面直接拼接 err.message 英文原文（如 "Request failed with status code 500"）的问题。

/**
 * 翻译错误对象为用户可读的中文提示
 * @param {Object} err axios 错误对象或 Error
 * @param {string} prefix 可选前缀，如 '上传失败: '
 * @returns {string} 中文提示（含原因与恢复方式）
 */
export function translateError(err, prefix = '') {
  // 1) 后端返回了明确的 detail：优先透传（后端 detail 已是人话）
  const detail = err?.response?.data?.detail
  if (detail) {
    return prefix + String(detail)
  }
  // 2) 浏览器侧错误（后端物理上无法感知，只能由前端翻译）
  const msg = String(err?.message || '')
  if (msg.includes('ERR_FILE_NOT_FOUND')) {
    return prefix + '部分所选文件已无法读取（可能已被移动/重命名/删除、U盘网络盘断开、或路径超长）——请重新选择文件'
  }
  if (msg.includes('ERR_CONNECTION_REFUSED')) {
    return prefix + '无法连接服务（服务未启动或正在重启）——请确认服务已启动后重试'
  }
  if (msg.includes('timeout')) {
    return prefix + '请求超时——文件较大时建议分批操作'
  }
  // 3) HTTP 状态码分类（有响应但无 detail）
  const status = err?.response?.status
  if (status) {
    if (status >= 500) {
      return prefix + `服务内部错误（${status}）——请查看服务窗口日志，或稍后重试`
    }
    if (status === 401) {
      return prefix + '登录状态已过期——请重新登录后再操作'
    }
    return prefix + `请求失败（${status}）`
  }
  // 4) 无响应无识别特征：网络层错误
  if (msg) {
    return prefix + '网络异常或服务不可达——请确认服务已启动后重试'
  }
  return prefix + '未知错误（详情见浏览器Console）'
}
