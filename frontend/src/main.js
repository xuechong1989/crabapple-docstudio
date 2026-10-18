import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import RootLayout from './RootLayout.vue'
import { useToast } from './composables/useToast'
// xuechong 2026-10-10 研发BUG-0071 用户复验：全站弹窗标题栏支持按住拖拽移动弹窗
import { setupDialogDrag } from './utils/dialogDrag'
import './styles/main.css'

const app = createApp(RootLayout)
app.use(createPinia())
app.use(router)
app.mount('#app')
setupDialogDrag()

// V3.1.01 xuechong 2026-07-25 版本自动检测：发现新版本后在下次页面导航时自动更新
// 解决浏览器缓存旧版 index.html 导致新版JS/CSS文件404的问题
// 不使用 reload()，避免强制刷新破坏用户登录会话
var _currentVersion = document.querySelector('meta[name="app-version"]')
var _appVersion = _currentVersion ? _currentVersion.content : ''
var _newVersionAvailable = false
// zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
// 版本不一致提示去重开关：提示一次即可，避免每30秒重复弹
var _versionToastShown = false
if (_appVersion) {
  // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
  // 检测到新版本时除"下次导航静默重载"外，同步弹出持久提示：旧逻辑用户停在单页
  // （如上传页）永远无感知版本已更新，前后端错配会表现为莫名的接口失败
  var _pollVersion = function () {
    fetch('/api')
      .then(function (res) { return res.json() })
      .then(function (data) {
        if (!data.version || data.version === _appVersion) {
          return
        }
        _newVersionAvailable = true
        if (_versionToastShown) {
          return
        }
        // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        // 版本不一致分两种情形，指引必须区分（用户反馈：刷新无效时提示"请刷新"是误导）：
        // 再拉一次磁盘上现行的 index.html 对比其 meta 版本——
        // 页面落后于磁盘前端 → 刷新即可拿到新版；
        // 页面已是磁盘最新但后端进程版本不同（git pull 后未重启服务）→ 刷新无用，需重启服务
        fetch('/', { cache: 'no-store' })
          .then(function (res) { return res.text() })
          .then(function (html) {
            var m = html.match(/name="app-version"\s+content="([^"]*)"/)
            var diskVersion = m ? m[1] : ''
            _versionToastShown = true
            if (diskVersion && diskVersion !== _appVersion) {
              useToast().showToast('检测到系统已更新到新版本（' + diskVersion + '），请刷新页面获取新版', 'warning', true)
            } else if (diskVersion) {
              useToast().showToast('前端版本（' + _appVersion + '）与服务器运行版本（' + data.version + '）不一致，请重启后端服务', 'warning', true)
            } else {
              useToast().showToast('检测到系统版本不一致（页面 ' + _appVersion + ' / 服务器 ' + data.version + '），请刷新页面；若仍提示请重启后端服务', 'warning', true)
            }
          })
          .catch(function () {
            _versionToastShown = true
            useToast().showToast('检测到系统版本不一致（页面 ' + _appVersion + ' / 服务器 ' + data.version + '），请刷新页面；若仍提示请重启后端服务', 'warning', true)
          })
      })
      .catch(function () {
        // 网络错误忽略，等待下次轮询
      })
  }
  // 启动时立即检查一次（原实现首查要等30秒，错过更新窗口）
  _pollVersion()
  setInterval(_pollVersion, 30000)

  // V3.1.01 xuechong 2026-07-25 监听路由变化，有新版本时在下一次导航自动加载新版页面
  router.afterEach(function () {
    if (_newVersionAvailable) {
      _newVersionAvailable = false
      // 通过重新赋值 location.href 触发正常导航（保留 cookie，不破坏会话）
      window.location.href = window.location.href
    }
  })
}
