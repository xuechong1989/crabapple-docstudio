<template>
  <div class="app-container">
    <!-- 全局Loading遮罩 -->
    <div v-if="globalLoading" class="global-loading-overlay">
      <div class="global-loading-content">
        <div class="global-loading-spinner"></div>
        <div class="global-loading-text">{{ globalLoadingText }}</div>
      </div>
    </div>

    <!-- 顶部标题栏 -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo-container">
          <img class="logo-icon" src="../assets/logo-white.png" alt="Logo" />
          <div class="title-text">
            <h1>海棠文档工坊</h1>
            <span class="version" @click="showVersionModal = true" title="点击查看版本说明">V3.4.00</span>
            <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：左上角除系统logo外不再常驻其他图标——
                 服务状态指示器改为仅网络中断时显示（在线告警信息移除，离线提醒保留） -->
            <span v-if="!serverOnline" class="service-status offline" title="后台服务已停止，请重启服务">
              <span class="status-dot">●</span>
              <span class="status-text">网络中断</span>
            </span>
          </div>
        </div>
      </div>
      <div class="header-right">
        <button v-if="authStore.isAdmin" class="version-btn" @click="showUserManagement = true" title="管理系统用户">
          <AppIcon name="users" /> 用户管理
        </button>
        <button class="version-btn" @click="showVersionModal = true" title="查看系统版本信息和更新日志，了解各版本的功能改进">
          <AppIcon name="clipboard" /> 版本说明
        </button>
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：操作手册按钮按用户要求全部隐藏（功能代码保留） -->
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：用户徽章统一放右上角最右侧（与功能页一致） -->
        <UserBadge :show-logout="true" />
      </div>
    </header>

    <!-- 首页功能入口区 -->
    <div class="home-portal">
      <div class="portal-container">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
             按用户要求删除门户页三处文字（"请选择您需要的功能"标题、"智能文档处理，让工作更高效"副标题、
             底部双层PDF提示条），页面只保留功能卡片 -->
        <div class="portal-cards">
          <!-- 图片转PDF入口 -->
          <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
               用户复验：卡片删描述句/特性标签/"点击进入"等文字，只留图标+标题+箭头 -->
          <div class="portal-card" @click="$router.push('/img-to-pdf')">
            <div class="card-icon-wrapper dual-icon">
              <AppIcon name="image" :size="34" class="card-icon" />
            </div>
            <h3 class="card-title">图转PDF</h3>
            <span class="action-arrow">→</span>
          </div>

          <!-- 编辑PDF入口 -->
          <div class="portal-card" @click="$router.push('/edit-pdf')">
            <div class="card-icon-wrapper edit-icon">
              <AppIcon name="edit" :size="34" class="card-icon" />
            </div>
            <h3 class="card-title">编辑PDF</h3>
            <span class="action-arrow">→</span>
          </div>
        </div>
      </div>

      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：底部版权页脚（灰色横线+居中的正规版权信息：
           产品名 | 公司版权，公司名带官网链接） -->
      <footer class="home-footer">
        <p>海棠文档工坊<span class="footer-sep">|</span>Copyright © {{ new Date().getFullYear() }} <a class="footer-company-link" href="https://github.com/xuechong1989/crabapple-docstudio" target="_blank" rel="noopener noreferrer">Crabapple DocStudio contributors</a> 版权所有</p>
      </footer>
    </div>

    <!-- zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 -->
    <!-- 本页内联 toast 渲染已移除：统一由 RootLayout 挂载的全局 ToastContainer 渲染（error 持久显示/点击复制/× 关闭） -->

    <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
         移除"进行中的任务"横幅：未完成任务恢复入口收拢到图片转PDF模块的"未完成任务"弹框，首页保持干净 -->

    <VersionModal v-model="showVersionModal" />
    <UserManagementModal :visible="showUserManagement" @close="showUserManagement = false" />
    
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as api from '../api'
import { useAuthStore } from '../stores/auth'
// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// 接入全局 useToast 单例（替换本页私有 toast 实现），渲染统一走 RootLayout 的 ToastContainer
import { useToast } from '../composables/useToast'
import VersionModal from '../components/VersionModal.vue'
import UserBadge from '../components/UserBadge.vue'
import UserManagementModal from '../components/UserManagementModal.vue'
// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 顶栏按钮与功能卡片图标：emoji 换单色线性 SVG 图标（AppIcon 纯展示组件）
import AppIcon from '../components/AppIcon.vue'

const isDev = import.meta.env.DEV
function devLog(level, ...args) { if (isDev) console[level](...args) }

const authStore = useAuthStore()

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 移除进行中任务横幅的全部逻辑
// （activeTasks/DISMISS_STORAGE_KEY/_loadDismissedIds/_saveDismissedIds/
//   dismissActiveTasks/statusLabel/checkActiveTasks 整体删除，恢复入口移至模块页弹框）

const globalLoading = ref(false)
const globalLoadingText = ref('')
function showGlobalLoading(text = '处理中，请稍候...') { globalLoadingText.value = text; globalLoading.value = true }
function hideGlobalLoading() { globalLoading.value = false; globalLoadingText.value = '' }

// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// 删除本页私有 toasts/showToast（3 秒自动消失的旧机制），统一使用全局 useToast：
// error 提示持久显示、点击文字复制全文、右侧 × 按钮关闭，与其他模块一致
const { showToast } = useToast()
const heartbeatTimer = ref(null)
const serverOnline = ref(true)
const serverOfflineShown = ref(false)
const heartbeatFailCount = ref(0)
const showVersionModal = ref(false)
const showUserManagement = ref(false)

function startHeartbeat() {
  checkServerStatus()
  heartbeatTimer.value = setInterval(checkServerStatus, 5000)
}

async function checkServerStatus() {
  try {
    await api.heartbeat()
    if (!serverOnline.value) { serverOnline.value = true; serverOfflineShown.value = false }
    heartbeatFailCount.value = 0
  } catch (err) {
    heartbeatFailCount.value++
    if (heartbeatFailCount.value >= 3 && !serverOfflineShown.value) {
      serverOnline.value = false; serverOfflineShown.value = true
      showToast('后台服务已停止，请重启服务', 'error')
    }
  }
}

function stopHeartbeat() {
  if (heartbeatTimer.value) { clearInterval(heartbeatTimer.value); heartbeatTimer.value = null }
}

function downloadUserManual() {
  const link = document.createElement('a')
  // xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 下载手册是浏览器直链，嵌入模式下走withEmbedToken拼嵌入参数，否则401
  link.href = api.withEmbedToken('/api/download-user-manual')
  link.download = '海棠文档工坊_用户操作手册.docx'
  document.body.appendChild(link); link.click(); document.body.removeChild(link)
}

onMounted(() => {
  devLog('log', '[App] 应用启动')
  startHeartbeat()
})

onUnmounted(() => { stopHeartbeat() })
</script>

<style>
/* 在 main.css 中定义样式 */
</style>
