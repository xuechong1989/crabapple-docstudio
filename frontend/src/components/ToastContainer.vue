<template>
  <div class="toast-container">
    <!-- zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 -->
    <!-- 错误类提示：点击文字复制全文（手动选中文字时不干预）、右侧 × 按钮关闭，不再点击整条关闭；
         复制成功后在警告条下方显示绿色"已复制"提示行（2026-09-04 用户反馈：同行的红色提示不够醒目） -->
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="[toast.type, toast.type === 'error' ? 'toast-stacked' : '']">
      <template v-if="toast.type === 'error'">
        <div class="toast-row">
          <span class="toast-message toast-copyable" title="点击复制全部内容" @click="copyToast(toast)">{{ toast.message }}</span>
          <button type="button" class="toast-close" title="关闭" @click.stop="dismissToast(toast.id)">&times;</button>
        </div>
        <div v-if="toast.copied" class="toast-copied-tip">&#10003; 已复制到剪贴板，可直接粘贴</div>
      </template>
      <template v-else>
        <span class="toast-message">{{ toast.message }}</span>
        <!-- zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取 -->
        <!-- 持久显示的非错误提示（如版本更新提示）同样提供 × 关闭按钮；普通 3 秒自动消失的提示无需按钮 -->
        <button v-if="toast.persistent" type="button" class="toast-close" title="关闭" @click.stop="dismissToast(toast.id)">&times;</button>
      </template>
    </div>
  </div>
  <!-- 错误弹框：不自动消失，需用户手动关闭 -->
  <Transition name="ds-modal">
  <div v-if="errorModal.visible" class="error-modal-overlay">
    <div class="error-modal">
      <div class="error-modal-header">
        <img class="dlg-logo" src="../assets/logo-white.png" alt="" />
        <span>系统异常</span>
      </div>
      <div class="error-modal-body">
        <p class="error-message">{{ errorModal.message }}</p>
        <pre v-if="errorModal.detail" class="error-detail">{{ errorModal.detail }}</pre>
      </div>
      <div class="error-modal-footer">
        <button class="error-modal-btn" @click="closeErrorModal()"><AppIcon name="check" :size="14" /> 确定</button>
      </div>
    </div>
  </div>
  </Transition>
</template>

<script setup>
// xuechong 2026-10-10 研发BUG-0071 用户复验：确定按钮补图标
import AppIcon from './AppIcon.vue'
import { useToast } from '../composables/useToast'
// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 引入 dismissToast 供错误提示点击关闭
// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 引入 copyToast 供错误提示文字点击复制，dismissToast 改由右侧 × 按钮调用
const { toasts, dismissToast, copyToast, errorModal, closeErrorModal } = useToast()
</script>

<style scoped>
/* zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 */
/* 错误提示文字区：光标呈文本样式，提示可点击复制、也可手动选中 */
.toast-copyable {
  cursor: text;
}

.error-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}
.error-modal {
  background: #fff;
  border-radius: 12px;
  width: 520px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}
.error-modal-header {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 6px 24px;
  background: #ff4d4f;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
}
.error-icon {
  font-size: 22px;
}
.error-modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}
.error-message {
  font-size: 15px;
  color: #333;
  margin: 0 0 12px 0;
  line-height: 1.6;
  word-break: break-word;
}
.error-detail {
  font-size: 14px;
  color: #888;
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 12px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', monospace;
}
.error-modal-footer {
  padding: 14px 24px;
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid #f0f0f0;
}
.error-modal-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 8px 32px;
  background: #ff4d4f;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
}
.error-modal-btn:hover {
  background: #ff7875;
}
</style>
