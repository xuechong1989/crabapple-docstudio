import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../pages/LoginPage.vue')
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('../pages/HomePage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/img-to-pdf',
    name: 'ImageToPdf',
    component: () => import('../pages/ImageToPdfPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/edit-pdf',
    name: 'EditPdf',
    component: () => import('../pages/EditPdfPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/dual-layer-pdf',
    name: 'DualLayerPdf',
    component: () => import('../pages/DualLayerPdfPage.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
// 进门核验标记：每个页面会话（打开页面到关闭）只向服务端核验一次登录态，不在每次切换页面时重复请求。
// 背景：此前本地有 token 就算已登录、从不向服务端核验，token 悄悄过期后页面看着一切正常，
// 直到上传等真正需要鉴权的操作才集中爆发 401；现在进门先核验一次，失效立即引导重新登录
let _sessionAuthVerified = false

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 嵌入模式标记：地址带embed参数时存入sessionStorage，图片转PDF页据此开启"任务列表1秒自动刷新"等
  // 仅嵌入模式生效的增强；普通直接访问（无此参数）不写标记，任何增强分支都不会走到
  // xuechong 2026-09-30 同需求追加：嵌入会话起始时刻（首次进入本页签会话时写入，重开页签自动更新）——
  // 嵌入页据它过滤"进入之前"的历史数据（任务/转换记录/上传记录），嵌入式不存在历史数据概念
  if (to.query.embed) {
    sessionStorage.setItem('ds_embed_mode', '1')
    if (!sessionStorage.getItem('ds_embed_session_at')) {
      sessionStorage.setItem('ds_embed_session_at', String(Date.now()))
    }
  }
  // xuechong 2026-09-27 嵌入免登录：地址带token且本地未登录时，用token建立登录态并把token参数从地址剥掉；
  // token无效时loginWithToken内部清除登录态，继续走未登录拦截回落到登录页
  // xuechong 2026-09-30 研发需求-0164 修正：地址带token时无条件用其重建登录态（不再要求本地未登录）——
  // 此前本地残留过期登录态（isLoggedIn=true）会让URL带来的新鲜token被跳过，全接口401"未登录"；
  // 嵌入页每次加载由form-in输出新鲜token，本地旧登录态一律让位
  if (to.query.token) {
    await auth.loginWithToken(String(to.query.token))
    const query = { ...to.query }
    delete query.token
    delete query.embed
    return { path: to.path, query: query, replace: true }
  }
  if (to.meta.requiresAuth) {
    // xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
    // 本地有登录态且本会话还没核验过时，先向服务端核验一次（fetchUserInfo 内部 401 时会清除登录态；
    // 网络错误等非 401 失败不清登录态，服务故障不误踢，后续操作自行报错）
    const hadLocalLogin = auth.isLoggedIn
    if (auth.isLoggedIn && !_sessionAuthVerified) {
      _sessionAuthVerified = true
      await auth.fetchUserInfo()
    }
    if (!auth.isLoggedIn) {
      // 核验前有本地登录态、核验后没了 = token 已失效，带原因让登录页显示"登录已过期"提示条
      if (hadLocalLogin) {
        return { path: '/login', query: { reason: 'expired' } }
      }
      return { path: '/login' }
    }
  }
})

export default router
