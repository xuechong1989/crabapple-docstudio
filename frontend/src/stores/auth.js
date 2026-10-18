// V3.1.01 xuechong 2026-07-25 认证 Store — JWT token 管理 + 用户信息
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '../api'

export const useAuthStore = defineStore('auth', () => {
  // xuechong 2026-06-01 核心状态
  const isLoggedIn = ref(false)
  const token = ref(null)
  const userInfo = ref(null)

  // V3.1.01 xuechong 2026-07-25 从 localStorage 恢复 token + 登录状态
  // 有 token 即认为已登录（token 无效时后端返回 401，拦截器会自动清除）
  // 避免页面刷新后 isLoggedIn 丢失导致误跳转登录页
  function _loadFromStorage() {
    try {
      const saved = localStorage.getItem('ds_auth')
      if (saved) {
        const data = JSON.parse(saved)
        token.value = data.token || null
        userInfo.value = data.user || null
        // V3.1.01: 有 token 即恢复登录状态，后端会验证 token 有效性
        isLoggedIn.value = !!data.token
      }
    } catch (e) { /* 忽略 */ }
  }

  // xuechong 2026-06-01 保存到 localStorage
  function _saveToStorage() {
    try {
      localStorage.setItem('ds_auth', JSON.stringify({
        token: token.value,
        user: userInfo.value
      }))
    } catch (e) {
      // 忽略存储错误
    }
  }

  // xuechong 2026-06-01 清除 localStorage
  function _clearStorage() {
    try {
      localStorage.removeItem('ds_auth')
    } catch (e) {
      // 忽略
    }
  }

  // xuechong 2026-06-01 登录（新版用户系统）
  async function login(username, password) {
    const res = await api.userLogin(username, password)
    if (res.data.success && res.data.token) {
      token.value = res.data.token
      userInfo.value = res.data.user
      isLoggedIn.value = true
      _saveToStorage()
      return { success: true }
    }
    return { success: false, message: res.data.message || '登录失败' }
  }

  // xuechong 2026-06-01 兼容旧版密码登录
  async function legacyLogin(hashedPassword) {
    const res = await api.verifyLogin(hashedPassword)
    if (res.data.success) {
      isLoggedIn.value = true
      // 如果返回了 token，也保存
      if (res.data.token) {
        token.value = res.data.token
        userInfo.value = res.data.user || null
        _saveToStorage()
      }
      return { success: true }
    }
    return { success: false, message: res.data.message || '口令错误' }
  }

  // xuechong 2026-06-01 注册
  async function register(username, password, displayName) {
    const res = await api.userRegister(username, password, displayName)
    if (res.data.success) {
      return { success: true }
    }
    return { success: false, message: res.data.detail || res.data.message || '注册失败' }
  }

  // xuechong 2026-06-01 登出
  function logout() {
    token.value = null
    userInfo.value = null
    isLoggedIn.value = false
    _clearStorage()
  }

  // xuechong 2026-09-27 嵌入免登录：用外部系统（电子文件系统嵌入页）随地址传入的token直接建立登录态，
  // 建立后立即向服务端刷新用户信息校验token有效性；token无效时fetchUserInfo内部会清除登录态
  async function loginWithToken(t) {
    if (!t) return false
    token.value = t
    isLoggedIn.value = true
    userInfo.value = null
    _saveToStorage()
    await fetchUserInfo()
    return isLoggedIn.value
  }

  // xuechong 2026-06-01 获取当前用户信息（从服务端刷新）
  async function fetchUserInfo() {
    if (!token.value) return null
    try {
      const res = await api.getCurrentUser()
      userInfo.value = res.data
      _saveToStorage()
      return res.data
    } catch (err) {
      if (err.response?.status === 401) {
        logout()
      }
      return null
    }
  }

  // xuechong 2026-06-01 是否管理员
  const isAdmin = computed(() => userInfo.value?.role === 'admin')

  // xuechong 2026-06-01 初始化：从 localStorage 恢复
  _loadFromStorage()

  return {
    isLoggedIn, token, userInfo, isAdmin,
    login, legacyLogin, register, logout, fetchUserInfo, loginWithToken
  }
})

// V3.1.01 xuechong 2026-07-25 注册 auth store 获取函数，供 API 拦截器在 token 刷新失败时调用 logout
api.registerAuthStoreGetter(() => useAuthStore())
