<template>
  <div class="login-overlay">
    <div class="login-modal">
      <div class="login-header">
        <div class="login-title-row">
          <img class="login-logo" src="../assets/logo-white.png" alt="Logo" />
          <h2>海棠文档工坊&nbsp;-&nbsp;V3.4.00</h2>
        </div>
      </div>
      <div class="login-body">
        <div class="login-form">
          <div class="form-group form-group-inline">
            <label>用户名</label>
            <div class="input-with-icon">
              <input type="text" v-model="loginUsername" placeholder="用户名（默认 admin）" @keyup.enter="handleLogin" class="login-input" />
            </div>
          </div>
          <div class="form-group form-group-inline">
            <label>口令</label>
            <div class="input-with-icon">
              <input type="password" v-model="loginPassword" placeholder="请输入口令" @keyup.enter="handleLogin" class="login-input" />
              <span v-if="capsLockOn" class="capslock-warning" title="大写锁定已开启">⇪</span>
            </div>
          </div>
          <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
               登录页本地访问免验证码（用户要求，仅 localhost/127.0.0.1 生效） -->
          <div v-if="!isLocalAccess" class="form-group form-group-inline captcha-group">
            <label>验证码</label>
            <div class="input-with-icon">
              <input type="text" v-model="loginCaptcha" placeholder="请输入验证码" @keyup.enter="handleLogin" class="login-input captcha-input" maxlength="4" />
            </div>
            <div class="captcha-image" @click="refreshCaptcha" title="点击刷新验证码">
              <canvas ref="captchaCanvas" width="120" height="40"></canvas>
            </div>
          </div>
          <!-- xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败 -->
          <!-- 登录过期被踢出到登录页时（地址带 reason=expired 参数）显示的提示条 -->
          <div v-if="sessionExpired" class="login-expired-tip">登录已过期，请重新登录</div>
          <div v-if="loginError" class="login-error">{{ loginError }}</div>
          <button class="login-btn" @click="handleLogin" :disabled="isLoggingIn">
            <span v-if="isLoggingIn">验证中...</span>
            <span v-else><AppIcon name="log-in" :size="14" /> 登 录</span>
          </button>
        </div>
      </div>
    </div>
    <!-- xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-登录页添加版权页脚
         结构与内容与首页 HomePage.vue 的 home-footer 完全一致（含横线），复用全局样式类；
         仅补 login-footer 定位类贴底（深色遮罩层内 flex 居中不受影响） -->
    <footer class="home-footer login-footer">
      <p>海棠文档工坊<span class="footer-sep">|</span>Copyright © {{ new Date().getFullYear() }} <a class="footer-company-link" href="https://github.com/xuechong1989/crabapple-docstudio" target="_blank" rel="noopener noreferrer">Crabapple DocStudio contributors</a> 版权所有</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import * as api from '../api'
import { computePasswordHash } from '../utils/crypto'
import AppIcon from '../components/AppIcon.vue'

const router = useRouter()
// xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
// 路由守卫或 401 拦截器发现登录态失效跳转过来时地址带 reason=expired，据此显示过期提示条
const route = useRoute()
const sessionExpired = route.query.reason === 'expired'
const authStore = useAuthStore()

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 登录页本地访问免验证码并预填管理员：
// 本机调试场景（localhost/127.0.0.1）免验证码+预填账号；非本地访问（如生产 IP）行为不变，验证码照常强制
const isLocalAccess = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const loginUsername = ref(isLocalAccess ? 'admin' : '')
const loginPassword = ref('')
const loginCaptcha = ref('')
const captchaText = ref('')
const captchaCanvas = ref(null)
const capsLockOn = ref(false)
const isLoggingIn = ref(false)
const loginError = ref('')

function generateCaptchaText() {
  const chars = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
  let text = ''
  for (let i = 0; i < 4; i++) text += chars[Math.floor(Math.random() * chars.length)]
  return text
}

function drawCaptcha() {
  const canvas = captchaCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width, h = canvas.height
  captchaText.value = generateCaptchaText()
  ctx.fillStyle = '#f0f0f0'
  ctx.fillRect(0, 0, w, h)
  for (let i = 0; i < 4; i++) {
    ctx.strokeStyle = `rgb(${Math.random()*150},${Math.random()*150},${Math.random()*150})`
    ctx.beginPath(); ctx.moveTo(Math.random()*w, Math.random()*h); ctx.lineTo(Math.random()*w, Math.random()*h); ctx.stroke()
  }
  for (let i = 0; i < 30; i++) {
    ctx.fillStyle = `rgb(${Math.random()*200},${Math.random()*200},${Math.random()*200})`
    ctx.beginPath(); ctx.arc(Math.random()*w, Math.random()*h, 1, 0, 2*Math.PI); ctx.fill()
  }
  ctx.font = 'bold 24px Arial'
  ctx.fillStyle = '#333'
  for (let i = 0; i < captchaText.value.length; i++) {
    ctx.save()
    ctx.translate(20 + i * 25, 25 + Math.random() * 10)
    ctx.rotate((Math.random() - 0.5) * 0.4)
    ctx.fillText(captchaText.value[i], 0, 0)
    ctx.restore()
  }
}

function refreshCaptcha() {
  drawCaptcha()
}

function checkCapsLock(e) {
  capsLockOn.value = e.getModifierState && e.getModifierState('CapsLock')
}

// xuechong 2026-06-26 computePasswordHash 已迁移到 ../utils/crypto.js

async function handleLogin() {
  loginError.value = ''
  if (!loginUsername.value.trim()) { loginError.value = '请输入用户名'; return }
  if (!loginPassword.value.trim()) { loginError.value = '请输入口令'; return }
  // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
  // 登录页本地访问免验证码：本地访问跳过验证码校验（验证码行已隐藏）；非本地仍强制
  if (!isLocalAccess) {
    if (!loginCaptcha.value.trim()) { loginError.value = '请输入验证码'; return }
    if (loginCaptcha.value.toUpperCase() !== captchaText.value.toUpperCase()) {
      loginError.value = '验证码错误'; refreshCaptcha(); return
    }
  }

  isLoggingIn.value = true
  try {
    const hashed = await computePasswordHash(loginPassword.value)
    const username = loginUsername.value.trim() || 'admin'

    let result = null
    try {
      result = await authStore.login(username, hashed)
    } catch (e) {
      // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
      // 区分服务故障与口令错误（原实现无差别吞掉走旧版链路，服务故障被误报为"用户名或密码错误"）：
      // 401/400=口令类业务错，保留旧版兼容链路；无响应或5xx=服务故障，明确提示不再误报
      const status = e.response?.status
      if (!e.response) {
        loginError.value = '无法连接服务，请确认服务已启动（bin\\start.bat）后重试'
        refreshCaptcha(); return
      }
      if (status >= 500) {
        loginError.value = `服务异常（${status}），请查看服务窗口日志或重启服务`
        refreshCaptcha(); return
      }
      /* 401/400 等业务错误：fallback 走旧版口令验证链路（原逻辑保留） */
    }

    if (!result || !result.success) {
      const res = await api.verifyLogin(hashed)
      if (res.data.success) {
        result = await authStore.legacyLogin(hashed)
      } else {
        loginError.value = '用户名或密码错误'; refreshCaptcha(); return
      }
    }

    if (result && result.success) {
      router.push('/')
    } else {
      loginError.value = result?.message || '登录失败'
      refreshCaptcha()
    }
  } catch (err) {
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    // 外层兜底错误翻译成人话（原实现直接显示英文 err.message 如 "Network Error"）
    if (!err.response) {
      loginError.value = '无法连接服务，请确认服务已启动后重试'
    } else {
      loginError.value = err.response?.data?.detail || `请求失败（${err.response.status}），请稍后重试或查看服务日志`
    }
    refreshCaptcha()
  } finally {
    isLoggingIn.value = false
  }
}

onMounted(() => {
  // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
  // 本地无验证码行，无需绘制
  if (!isLocalAccess) nextTick(() => drawCaptcha())
  // 已登录直接跳首页
  if (authStore.isLoggedIn) router.push('/')
})
</script>

<style scoped>
/* xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败 */
/* 登录过期提示条：黄色系提示，与口令错误的红色 login-error 区分 */
.login-expired-tip {
  color: #8a6d3b;
  background: #fcf8e3;
  border: 1px solid #faebcc;
  border-radius: 6px;
  padding: 10px 14px;
  margin: 8px 0;
  font-size: 14px;
  font-weight: 600;
  text-align: center;
}
.login-error {
  color: #d32f2f;
  background: #ffebee;
  border: 1px solid #ef9a9a;
  border-radius: 6px;
  padding: 10px 14px;
  margin: 8px 0;
  font-size: 14px;
  font-weight: 600;
  text-align: center;
  animation: shake 0.4s ease-in-out;
}
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-6px); }
  75% { transform: translateX(6px); }
}
</style>
