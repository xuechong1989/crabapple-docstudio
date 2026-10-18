<!-- xuechong 2026-06-01 用户标签组件 — 显示当前登录用户 -->
<!-- xuechong 2026-10-10 研发BUG-0071 用户复验：退出按钮改为悬停下拉菜单项
     （鼠标滑到徽章上自动下拉显示"退出登录"，与模式下拉/上传下拉同一交互模式） -->
<template>
  <div
    v-if="auth.isLoggedIn && displayName"
    class="user-badge"
    :title="'当前用户: ' + displayName"
    @mouseenter="showLogout && (menuOpen = true)"
    @mouseleave="menuOpen = false"
  >
    <span class="user-badge-avatar">{{ displayName.charAt(0) }}</span>
    <span class="user-badge-name">{{ displayName }}</span>
    <AppIcon v-if="showLogout" name="chevron-down" :size="12" class="user-badge-caret" />
    <div v-if="menuOpen && showLogout" class="user-badge-menu">
      <button class="user-badge-menu-item" @click="handleLogout">
        <AppIcon name="log-out" :size="14" /> 退出登录
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  showLogout: { type: Boolean, default: true }
})

const auth = useAuthStore()
const router = useRouter()

const menuOpen = ref(false)

const displayName = computed(() => {
  if (auth.userInfo) {
    return auth.userInfo.display_name || auth.userInfo.username || ''
  }
  // 兼容模式：只有 isLoggedIn 没有 userInfo
  if (auth.isLoggedIn) return '管理员'
  return ''
})

function handleLogout() {
  menuOpen.value = false
  auth.logout()
  // V3.1.01 xuechong 2026-07-25 直接跳转登录页，避免在首页时 router.push('/') 不触发路由守卫
  router.push('/login')
}
</script>

<style scoped>
/* xuechong 2026-10-10 研发BUG-0071 用户复验：用户徽章白玻璃质感（与橙色顶栏按钮同体系），
   退出按钮改为悬停下拉菜单项（不再平铺显示） */
.user-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px 0 4px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.25) 0%, rgba(255, 255, 255, 0.12) 100%);
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 16px;
  font-size: 14px;
  color: #fff;
  font-weight: 600;
  white-space: nowrap;
  cursor: default;
  transition: all 0.2s;
  backdrop-filter: blur(10px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.user-badge:hover {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.38) 0%, rgba(255, 255, 255, 0.2) 100%);
  border-color: rgba(255, 255, 255, 0.55);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.3);
}
.user-badge-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary-light, #F97316) 0%, var(--primary-color, #EA580C) 100%);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.4), inset 0 1px 1px rgba(255, 255, 255, 0.4);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  text-transform: uppercase;
}
.user-badge-name {
  font-weight: 600;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}
.user-badge-caret {
  opacity: 0.85;
}
/* 退出下拉菜单：与上传下拉同款（白底、贴徽章下缘、右对齐） */
.user-badge-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 128px;
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.18);
  z-index: 200;
  overflow: hidden;
  padding: 4px;
}
.user-badge-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  background: none;
  font-family: inherit;
  font-size: 14px;
  color: #DC2626;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}
.user-badge-menu-item:hover {
  background: #FEF2F2;
}
</style>
