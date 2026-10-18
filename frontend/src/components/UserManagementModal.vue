<!-- xuechong 2026-06-02 用户管理弹窗（仅管理员可见） -->
<template>
  <!-- xuechong 2026-10-09 研发BUG-0071 弹框交互统一：点击遮罩关闭（.self 防点内容误关） -->
  <Transition name="ds-modal">
  <div v-if="visible" class="itp-history-overlay">
    <div class="itp-history-dialog itp-history-dialog-lg">
      <div class="itp-history-header">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 emoji 换单色线性 SVG（提示文字中的⚠为文本符号保留） -->
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />用户管理</h4>
        <button class="itp-history-close" @click="$emit('close')">&times;</button>
      </div>
      <div class="itp-history-body">
        <div class="itp-history-table-wrap">
          <table class="itp-history-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>显示名称</th>
                <th>角色</th>
                <th>创建时间</th>
                <th>最后登录</th>
                <th class="col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="users.length === 0" class="itp-history-empty-row">
                <td colspan="6">暂无用户数据</td>
              </tr>
              <tr v-for="user in paginatedUsers" :key="user.username">
                <td><span class="user-name-cell">{{ user.username }}</span></td>
                <td>{{ user.display_name || user.username }}</td>
                <td>
                  <span :class="user.role === 'admin' ? 'role-badge-admin' : 'role-badge-user'">
                    {{ user.role === 'admin' ? '管理员' : '普通用户' }}
                  </span>
                </td>
                <td class="time-cell">{{ fmtTime(user.created_at) }}</td>
                <td class="time-cell">
                  <span v-if="user.last_login" :title="user.last_login">{{ fmtTime(user.last_login) }}</span>
                  <span v-else style="color:#ccc;">从未登录</span>
                </td>
                <td class="action-cell" style="display:flex;gap:4px;">
                  <template v-if="user.username !== currentUsername">
                    <button class="itp-btn itp-btn-primary itp-btn-sm" @click="handleResetPwd(user)"><AppIcon name="refresh-cw" :size="12" /> 重置密码</button>
                    <button class="itp-btn itp-btn-danger itp-btn-sm" @click="handleDeleteUser(user)"><AppIcon name="trash" :size="12" /> 删除</button>
                  </template>
                  <span v-else style="color:#ccc;font-size:12px;">当前用户</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：分页组件与转换记录弹框统一 -->
        <div v-if="sortedUsers.length > 0" class="itp-history-pagination">
          <button class="page-btn" :disabled="currentPage === 1" @click="currentPage = 1">首页</button>
          <button class="page-btn" :disabled="currentPage === 1" @click="currentPage--">上一页</button>
          <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
          <button class="page-btn" :disabled="currentPage === totalPages" @click="currentPage++">下一页</button>
          <button class="page-btn" :disabled="currentPage === totalPages" @click="currentPage = totalPages">末页</button>
          <select v-model="pageSize" class="page-size-select">
            <option :value="10">10条/页</option>
            <option :value="20">20条/页</option>
            <option :value="50">50条/页</option>
          </select>
          <span class="history-total">共 {{ sortedUsers.length }} 个用户</span>
        </div>
      </div>
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：创建用户按钮按正常系统设计逻辑放弹窗
           底部操作栏（列表内容+底部右侧主操作，不再挤在标题栏） -->
      <div class="um-footer">
        <button class="itp-btn itp-btn-primary" @click="openCreateDialog"><AppIcon name="plus" :size="13" /> 创建用户</button>
      </div>
    </div>

    <!-- 创建用户弹框 -->
    <!-- xuechong 2026-10-09 研发BUG-0071 表单弹框不提供遮罩关闭：填写中误点外部丢表单内容 -->
    <Transition name="ds-modal">
    <div v-if="showCreate" class="itp-history-overlay" style="z-index:10002;">
      <div class="itp-history-dialog" style="height:auto;min-height:auto;max-width:460px;">
        <div class="itp-history-header">
          <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：标题栏左上角只留logo+文字，去除装饰符号＋ -->
          <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />创建新用户</h4>
          <button class="itp-history-close" @click="showCreate = false">&times;</button>
        </div>
        <div class="itp-history-body" style="min-height:auto;">
        <div class="create-form">
          <div class="create-field">
            <label>用户名 <span style="color:red;">*</span></label>
            <input v-model="createForm.username" placeholder="2-32位字母数字或下划线" class="create-input" maxlength="32" />
          </div>
          <div class="create-field">
            <label>登录密码 <span style="color:red;">*</span></label>
            <div class="create-pwd-row">
              <input v-model="createForm.password" type="text" placeholder="输入密码或点击生成" class="create-input" style="flex:1;" />
              <button class="itp-btn itp-btn-default itp-btn-sm" @click="generatePwd"><AppIcon name="shuffle" :size="14" /> 随机生成</button>
            </div>
          </div>
          <div class="create-field">
            <label>显示名称</label>
            <input v-model="createForm.displayName" placeholder="如：张三（不填则使用用户名）" class="create-input" maxlength="32" />
          </div>
          <div class="create-field">
            <label>角色</label>
            <select v-model="createForm.role" class="create-input">
              <option value="user">普通用户</option>
            </select>
          </div>
        </div>
        <div class="unsaved-actions">
          <button class="itp-btn itp-btn-primary" @click="confirmCreate" :disabled="!createForm.username || !createForm.password"><AppIcon name="check" :size="13" /> 确认创建</button>
          <button class="itp-btn itp-btn-default" @click="showCreate = false"><AppIcon name="x" :size="13" /> 取消</button>
        </div>
        </div><!-- .itp-history-body -->
      </div><!-- .itp-history-dialog -->
    </div><!-- .itp-history-overlay -->
    </Transition>

    <!-- 删除用户确认框 -->
    <Transition name="ds-modal">
    <div v-if="showDeleteUserConfirm" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog" style="width:400px;">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />删除用户</h4>
        <p>确定要删除用户 <strong>{{ deleteTarget?.username }}</strong> 吗？</p>
        <p style="font-size:13px;color:#DC2626;">该用户的所有上传记录、操作历史等数据将被永久删除！</p>
        <div class="unsaved-actions">
          <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：确认框按钮顺序统一为取消左/动作右 -->
          <button class="itp-btn itp-btn-default" @click="showDeleteUserConfirm = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-danger" @click="confirmDeleteUser"><AppIcon name="trash" :size="13" /> 确认删除</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 重置密码确认框 -->
    <Transition name="ds-modal">
    <div v-if="showResetConfirm" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog" style="width:400px;">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />重置密码</h4>
        <p>确定要重置用户 <strong>{{ resetTarget?.username }}</strong> 的密码吗？</p>
        <p style="font-size:13px;color:#888;">新密码将在重置后显示，请及时告知用户。</p>
        <div class="unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="showResetConfirm = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-primary" @click="confirmReset"><AppIcon name="check" :size="13" /> 确认重置</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 新密码显示 -->
    <Transition name="ds-modal">
    <div v-if="showNewPassword" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog" style="width:420px;">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />{{ pwdDialogMode === 'create' ? '创建成功' : '密码已重置' }}</h4>
        <p v-if="pwdDialogMode === 'create'">用户 <strong>{{ resetTarget?.username }}</strong> 创建成功，初始密码为：</p>
        <p v-else>用户 <strong>{{ resetTarget?.username }}</strong> 的新密码为：</p>
        <div class="new-pwd-display">{{ newPassword }}</div>
        <p style="font-size:12px;color:#DC2626;">⚠ 此密码仅显示一次，请立即复制并告知用户</p>
        <div class="unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="showNewPassword = false"><AppIcon name="x" :size="13" /> 关闭</button>
          <button class="itp-btn itp-btn-primary" @click="copyAndClose"><AppIcon name="clipboard" :size="13" /> 复制密码并关闭</button>
        </div>
      </div>
    </div>
    </Transition>
  </div>
  </Transition>
</template>

<script setup>
import { ref, watch, computed, reactive } from 'vue'
import { useAuthStore } from '../stores/auth'
import api from '../api'
import * as apiNamed from '../api'
import { computePasswordHash } from '../utils/crypto'
import { useToast } from '../composables/useToast'

// xuechong 2026-10-10 研发BUG-0071 用户复验：失败提示改全局toast（原原生alert）
const { showToast } = useToast()
// xuechong 2026-10-09 研发BUG-0071 图标组件：本弹窗 emoji 换单色线性 SVG
import AppIcon from './AppIcon.vue'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
const auth = useAuthStore()
const currentUsername = computed(() => auth.userInfo?.username || 'admin')

const users = ref([])
const showCreate = ref(false)
const showResetConfirm = ref(false)
const showNewPassword = ref(false)
// 密码展示弹框模式：reset=密码已重置 / create=创建成功（原alert改站内弹框）
const pwdDialogMode = ref('reset')
const resetTarget = ref(null)
const newPassword = ref('')
const showDeleteUserConfirm = ref(false)
const deleteTarget = ref(null)

const createForm = reactive({
  username: '',
  password: '',
  displayName: '',
  role: 'user'
})

function fmtTime(iso) {
  if (!iso) return ''
  try { const d = new Date(iso); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` } catch { return iso }
}

async function loadUsers() {
  try {
    const res = await api.get('/auth/users')
    users.value = res.data.users || []
  } catch (e) { /* 静默 */ }
}

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 用户管理列表排序：按创建时间倒序为主、最后登录倒序为辅（无最后登录记录的排最后），最新用户始终在最上
const sortedUsers = computed(() => {
  const ts = v => (v ? new Date(v).getTime() || 0 : 0)
  return [...users.value].sort((a, b) => {
    const d = ts(b.created_at) - ts(a.created_at)
    if (d !== 0) return d
    return ts(b.last_login) - ts(a.last_login)
  })
})

// xuechong 2026-10-10 研发BUG-0071 用户复验：用户管理列表分页——复用转换记录弹框同款
// 分页组件（itp-history-pagination，首页/上一页/页码/下一页/末页/每页条数/总数）
const currentPage = ref(1)
const pageSize = ref(10)
const totalPages = computed(() => Math.ceil(sortedUsers.value.length / pageSize.value) || 1)
const paginatedUsers = computed(() => {
  const s = (currentPage.value - 1) * pageSize.value
  return sortedUsers.value.slice(s, s + pageSize.value)
})
watch([() => sortedUsers.value.length, pageSize], () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
  currentPage.value = Math.max(1, currentPage.value)
})

function generatePwd() {
  const chars = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  let pwd = ''
  for (let i = 0; i < 12; i++) pwd += chars[Math.floor(Math.random() * chars.length)]
  createForm.password = pwd
}

function openCreateDialog() {
  createForm.username = ''
  createForm.password = ''
  createForm.displayName = ''
  createForm.role = 'user'
  showCreate.value = true
}

async function confirmCreate() {
  if (!createForm.username.trim() || !createForm.password.trim()) return
  try {
    // 前端 SHA-256 哈希密码
    const hashedPassword = await computePasswordHash(createForm.password)
    const res = await apiNamed.userRegister(createForm.username.trim(), hashedPassword, createForm.displayName.trim(), createForm.role)
    if (res.data.success) {
      showCreate.value = false
      await loadUsers()
      // xuechong 2026-10-10 研发BUG-0071 用户复验：创建成功改站内密码展示弹框（原原生alert）
      resetTarget.value = { username: createForm.username.trim() }
      newPassword.value = createForm.password
      pwdDialogMode.value = 'create'
      showNewPassword.value = true
      createForm.username = ''
      createForm.password = ''
    } else {
      showToast('创建失败：' + (res.data.message || res.data.detail || '未知错误'), 'error')
    }
  } catch (e) {
    showToast('创建失败：' + (e.response?.data?.detail || e.message), 'error')
  }
}

// xuechong 2026-06-26 computeHash 已迁移到 ../utils/crypto.js（统一使用 computePasswordHash）

function handleResetPwd(user) {
  resetTarget.value = user
  showResetConfirm.value = true
}

function handleDeleteUser(user) {
  deleteTarget.value = user
  showDeleteUserConfirm.value = true
}

async function confirmDeleteUser() {
  if (!deleteTarget.value) return
  try {
    await api.delete(`/auth/users/${deleteTarget.value.username}`)
    showDeleteUserConfirm.value = false
    deleteTarget.value = null
    await loadUsers()
  } catch (e) {
    showToast('删除失败: ' + (e.response?.data?.detail || e.message), 'error')
    showDeleteUserConfirm.value = false
  }
}

async function confirmReset() {
  if (!resetTarget.value) return
  try {
    const res = await api.post(`/auth/users/${resetTarget.value.username}/reset-password`, {})
    if (res.data.success) {
      newPassword.value = res.data.new_password
      showResetConfirm.value = false
      pwdDialogMode.value = 'reset'
      showNewPassword.value = true
    }
  } catch (e) {
    showToast('重置失败: ' + (e.response?.data?.detail || e.message), 'error')
    showResetConfirm.value = false
  }
}

async function copyAndClose() {
  // xuechong 2026-06-26 剪贴板写入（兼容 HTTP 非安全上下文）
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(newPassword.value)
    } else {
      // xuechong 2026-06-26 降级方案：使用 execCommand('copy')
      const textarea = document.createElement('textarea')
      textarea.value = newPassword.value
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
  } catch { /* 忽略复制失败 */ }
  showNewPassword.value = false
  resetTarget.value = null
  newPassword.value = ''
  emit('close')
}

watch(() => props.visible, v => { if (v) loadUsers() })
</script>

<style scoped>
.user-name-cell { font-weight: 600; }
/* xuechong 2026-10-10 研发BUG-0071 用户复验：弹窗底部操作栏（顶部分隔线+右侧主操作按钮） */
.um-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  padding: 12px 0 0;
  margin-top: 12px;
  border-top: 1px solid #E5E7EB;
  flex-shrink: 0;
}
.role-badge-admin { display:inline-block;padding:1px 8px;border-radius:10px;background:#fff3e0;color:#e65100;font-size:12px;font-weight:600; }
.role-badge-user  { display:inline-block;padding:1px 8px;border-radius:10px;background:#e8f5e9;color:#2e7d32;font-size:12px; }
.time-cell { font-size:13px;color:#666; }

/* xuechong 2026-10-10 研发BUG-0071 用户复验：本组件旧版 itp-unsaved 私有样式整组删除——
   scoped 属性选择器优先级高于 main.css 全局标准，导致确认框橙头变"白卡内悬浮橙条"
   （h4 负边距被 margin:0 0 16px 覆盖）。统一吃 main.css 标准确认弹框（通栏橙头+白logo） */

.create-form { display:flex;flex-direction:column;gap:14px; }
.create-field { display:flex;flex-direction:column;gap:4px; }
.create-field label { font-size:13px;font-weight:600;color:#333; }
.create-input { padding:9px 12px;border:1px solid #d9d9d9;border-radius:6px;font-size:14px;outline:none;transition:border-color 0.2s; }
/* xuechong 2026-10-09 研发BUG-0071 内联旧橙 #ff7f00 并入主色 */
.create-input:focus { border-color:var(--primary-color,#B3123B);box-shadow:0 0 0 2px rgba(234,88,12,0.1); }
.create-pwd-row { display:flex;gap:8px;align-items:center; }

.new-pwd-display { padding:16px;margin:12px 0;background:#f5f5f5;border:2px dashed var(--primary-color,#B3123B);border-radius:8px;font-size:22px;font-weight:700;text-align:center;color:var(--primary-color,#B3123B);letter-spacing:2px;font-family:'Courier New',monospace; }
</style>
