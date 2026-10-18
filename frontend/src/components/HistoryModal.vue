<template>
<!-- xuechong 2026-10-09 研发BUG-0071 弹框交互统一：浏览类弹框支持点击遮罩关闭 -->
  <Transition name="ds-modal">
  <div v-if="visible" class="itp-history-overlay">
    <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
         转换记录加宽类：本次加勾选列与重命名列后表格12列变宽，加宽弹框尽量不出横向滚动条；
         上传记录弹框（isUpload）不加，尺寸保持原样 -->
    <div class="itp-history-dialog itp-history-dialog-lg" :class="{ 'itp-history-dialog-wide': !isUpload }">
      <div class="itp-history-header">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />{{ isUpload ? '上传记录' : '转换记录' }}</h4>
        <button class="itp-history-close" @click="$emit('close')">&times;</button>
      </div>
      <div class="itp-history-body">

        <!-- 转换记录：下载历史表格 -->
        <div v-if="!isUpload" class="itp-history-table-wrap">
          <table class="itp-history-table">
            <thead>
              <tr>
                <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                     行首勾选列：表头复选框全选/取消当前页，配合底部批量下载按钮 -->
                <th class="col-check"><input type="checkbox" class="itp-history-checkall" :checked="allCurrentPageSelected" @change="toggleSelectCurrentPage" /></th>
                <!-- xuechong 2026-06-30 删除序号列 -->
                <th>文件名称</th>
                <th class="col-count">文件数</th>
                <th>保存时间</th>
                <th class="col-dl-count">下载次数</th>
                <th class="col-dl-count">编辑状态</th>
                <th class="col-dl-count">编辑后下载</th>
                <th class="col-action">下载</th>
                <th class="col-action">预览</th>
                <th class="col-action">重命名</th>
                <th class="col-action">编辑</th>
                <th class="col-action">删除</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="list.length === 0">
                <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                     本次同时加了勾选列和重命名列，空态行占位列数从 10 变 12 -->
                <tr class="itp-history-empty-row"><td colspan="12">暂无转换记录</td></tr>
              </template>
              <template v-else>
                <tr v-for="(item, idx) in paginatedList" :key="currentPage * pageSize + idx"
                  :class="{ 'not-downloaded': (item.download_count || 0) === 0 }">
                  <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                       行勾选框：按 task_id 记忆勾选（翻页不丢、删除记录后不错位） -->
                  <td class="check-cell"><input type="checkbox" class="itp-history-check" :checked="selectedTaskIds.has(item.task_id)" @change="toggleSelect(item.task_id)" /></td>
                  <td class="name-cell" :title="item.folder_name || item.name || 'PDF文件'">
                    <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                         重命名编辑态：该行名称变为输入框，回车确认上抛父页面校验并调接口；
                         Esc放弃；点到别处（失焦）时名字有改动静默保存、没改动直接退出 -->
                    <div v-if="renamingIndex === getGlobalIndex(idx)" class="itp-rename-box">
                      <input :ref="setRenameEl" v-model="renameInput" class="itp-rename-input" placeholder="请输入新文件名，无需带 .pdf 后缀"
                        @keyup.enter="confirmRename(getGlobalIndex(idx))"
                        @keyup.esc="cancelRename"
                        @blur="handleRenameBlur(getGlobalIndex(idx))" />
                    </div>
                    <template v-else>{{ item.first_image_name || item.folder_name || item.name || 'PDF文件' }}</template>
                  </td>
                  <td class="count-cell">{{ item.file_count || '-' }}</td>
                  <td class="time-cell">{{ item.created_at || item.time || '' }}</td>
                  <td class="dl-count-cell">{{ item.download_count || 0 }}</td>
                  <td class="dl-count-cell">
                    <span v-if="item.edited" style="color:var(--primary-color, #B3123B);font-weight:600;">已编辑</span>
                    <span v-else style="color:#999;">未编辑</span>
                  </td>
                  <td class="dl-count-cell">{{ item.edit_download_count || 0 }}</td>
                  <td class="action-cell"><button class="itp-btn itp-btn-success itp-btn-sm" @click="$emit('download', getGlobalIndex(idx))"><AppIcon name="download" :size="12" /> 下载</button></td>
                  <td class="action-cell"><button class="itp-btn itp-btn-primary itp-btn-sm" @click="$emit('preview', getGlobalIndex(idx))"><AppIcon name="eye" :size="12" /> 预览</button></td>
                  <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                       重命名按钮：与编辑/删除同口径，一键修图/批量修图进行中禁用；
                       预填当前显示名（与显示链一致多兜两级，极端旧记录也有名字可改） -->
                  <td class="action-cell"><button class="itp-btn itp-btn-edit itp-btn-sm" :disabled="actionsLocked" @click="startRename(getGlobalIndex(idx), item.first_image_name || item.folder_name || item.name || '')"><AppIcon name="edit" :size="12" /> 重命名</button></td>
                  <!-- xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中记录弹框只留
                       下载/预览查看类，编辑（跳转编辑PDF会中断流程）/删除禁用 -->
                  <td class="action-cell"><button class="itp-btn itp-btn-edit itp-btn-sm" :disabled="actionsLocked" @click="$emit('edit', getGlobalIndex(idx))"><AppIcon name="edit" :size="12" /> 编辑</button></td>
                  <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
                       删除行前先退出重命名编辑态：删除会让后面的行索引前移，
                       不退出的话输入框会错位跳到相邻行 -->
                  <td class="action-cell"><button class="itp-btn itp-btn-danger itp-btn-sm" :disabled="actionsLocked" @click="handleDeleteClick(getGlobalIndex(idx))"><AppIcon name="trash" :size="12" /> 删除</button></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- 上传记录表格 -->
        <div v-else class="itp-history-table-wrap">
          <table class="itp-history-table">
            <thead>
              <tr>
                <!-- xuechong 2026-06-30 删除序号列 -->
                <th>文件夹名称</th>
                <th class="col-count">文件数</th>
                <th>上传时间</th>
                <th class="col-status">状态</th>
                <th>备注</th>
                <th class="col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="list.length === 0">
                <!-- xuechong 2026-06-30 删除序号列，colspan 从 7 改为 6 -->
                <tr class="itp-history-empty-row"><td colspan="6">暂无上传记录</td></tr>
              </template>
              <template v-else>
                <tr v-for="(item, idx) in paginatedList" :key="currentPage * pageSize + idx">
                  <!-- xuechong 2026-06-30 删除序号列 -->
                  <td class="name-cell" :title="item.folder_name">{{ item.folder_name }}</td>
                  <td class="count-cell">{{ item.file_count || item.total_files || '-' }}</td>
                  <td class="time-cell">{{ _fmt(item.created_at) }}</td>
                  <td class="status-cell">
                    <span :class="'upload-status-tag upload-status-' + item.status">{{ _status(item.status) }}</span>
                  </td>
                  <td class="msg-cell" :title="item.last_message">{{ item.last_message || '' }}</td>
                  <td class="action-cell" style="display:flex;gap:4px;">
                    <!-- xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中"继续上传"会重载任务打断流程，禁用 -->
                    <button class="itp-btn itp-btn-primary itp-btn-sm" :disabled="actionsLocked" @click="$emit('resume-upload', item.task_id)"><AppIcon name="play" :size="12" /> 继续</button>
                    <button class="itp-btn itp-btn-danger itp-btn-sm" :disabled="actionsLocked" @click="handleDeleteUpload(item.task_id)"><AppIcon name="trash" :size="12" /> 删除</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
           转换记录批量下载操作条：勾选若干条后一次下载一个ZIP；一条未勾时置灰（仅转换记录显示） -->
      <div v-if="!isUpload && list.length > 0" class="itp-history-batch-bar">
        <button class="itp-btn itp-btn-success itp-btn-sm" :disabled="selectedTaskIds.size === 0" @click="emitBatchDownload">
          <AppIcon name="package" :size="12" /> 批量下载<template v-if="selectedTaskIds.size > 0">({{ selectedTaskIds.size }})</template>
        </button>
      </div>

      <!-- 分页 -->
      <div v-if="list.length > 0" class="itp-history-pagination">
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
        <span class="history-total">共 {{ list.length }} 条</span>
      </div>
    </div>
  </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, reactive, nextTick, shallowRef } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  visible: Boolean,
  // mode: 'download' | 'upload'
  mode: { type: String, default: 'download' },
  // 数据列表（下载历史或上传历史）
  list: { type: Array, default: () => [] },
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中修改类按钮（编辑/删除/继续）禁用
  actionsLocked: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'preview', 'download', 'edit', 'delete', 'delete-upload', 'resume-upload', 'rename', 'batch-download'])

const isUpload = computed(() => props.mode === 'upload')

const currentPage = ref(1)
const pageSize = ref(10)

const totalPages = computed(() => Math.ceil(props.list.length / pageSize.value) || 1)

const paginatedList = computed(() => {
  const s = (currentPage.value - 1) * pageSize.value
  return props.list.slice(s, s + pageSize.value)
})

function getGlobalIndex(i) { return (currentPage.value - 1) * pageSize.value + i }

function _status(s) {
  const m = { uploaded: '等待处理', processing: '处理中', completed: '已生成PDF', failed: '处理失败', cancelled: '已取消' }
  return m[s] || s || '未知'
}
function _fmt(iso) {
  if (!iso) return ''
  try { const d = new Date(iso); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}` } catch { return iso }
}

// xuechong 2026-10-10 研发BUG-0071 用户复验：上传记录删除不再用浏览器原生confirm，
// 直接上抛由父页面弹统一站内确认框（与转换记录删除一致）
function handleDeleteUpload(taskId) {
  emit('delete-upload', taskId)
}

// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 转换记录勾选状态：按 task_id 记忆（翻页不丢、删除某条记录后其余勾选不错位）；
// 弹框关闭或列表整体重新加载时清空
const selectedTaskIds = reactive(new Set())
// 正在重命名的记录全局索引（null 表示没有行处于编辑态）
const renamingIndex = ref(null)
const renameInput = ref('')

// 当前页是否全部勾选（表头全选框的选中状态）
const allCurrentPageSelected = computed(() =>
  paginatedList.value.length > 0 && paginatedList.value.every(item => selectedTaskIds.has(item.task_id)))

function toggleSelect(taskId) {
  if (selectedTaskIds.has(taskId)) {
    selectedTaskIds.delete(taskId)
  } else {
    selectedTaskIds.add(taskId)
  }
}

// 表头全选/取消全选：只作用于当前页的记录
function toggleSelectCurrentPage(e) {
  const checked = e.target.checked
  paginatedList.value.forEach(item => {
    if (checked) {
      selectedTaskIds.add(item.task_id)
    } else {
      selectedTaskIds.delete(item.task_id)
    }
  })
}

// 进入重命名编辑态：输入框预填当前显示名，聚焦并全选（用户通常整体重输）
// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 聚焦必须用函数式ref：v-for里的字符串模板ref会被Vue3收集成数组（拿到的值没有focus方法，
// 调用静默失败，点重命名后焦点切不过去）；函数式ref在元素挂载时以元素本身调用、卸载时传null
const renameInputEl = shallowRef(null)
const renameInitial = ref('')
function setRenameEl(el) {
  renameInputEl.value = el
}
function startRename(globalIndex, currentName) {
  renamingIndex.value = globalIndex
  renameInput.value = currentName || ''
  renameInitial.value = currentName || ''
  nextTick(() => {
    if (renameInputEl.value) {
      renameInputEl.value.focus()
      renameInputEl.value.select()
    }
  })
}

function cancelRename() {
  renamingIndex.value = null
  renameInput.value = ''
  renameInitial.value = ''
}

// 点确定/回车：校验与接口调用在父页面（统一走主页面toast提示），组件只上抛新名字并退出编辑态
function confirmRename(globalIndex) {
  const newName = renameInput.value
  cancelRename()
  emit('rename', globalIndex, newName)
}

// 失焦保存：名字有改动静默提交，没改动直接退出不惊动用户；
// 回车路径退出编辑态后输入框随v-if移除、个别浏览器仍派发blur，行号对不上直接忽略避免重复提交
function handleRenameBlur(globalIndex) {
  if (renamingIndex.value !== globalIndex) {
    return
  }
  const changed = (renameInput.value || '').trim() !== (renameInitial.value || '').trim()
  if (changed) {
    confirmRename(globalIndex)
  } else {
    cancelRename()
  }
}

// 批量下载：把勾选的task_id映射回当前列表的全局索引上抛（已被删除的记录不在列表里，自动跳过）
function emitBatchDownload() {
  const indices = []
  props.list.forEach((item, i) => {
    if (selectedTaskIds.has(item.task_id)) {
      indices.push(i)
    }
  })
  if (indices.length === 0) {
    // 勾选的记录已全部被删除：清掉残留勾选，避免按钮计数虚高到下次重开弹框
    selectedTaskIds.clear()
    return
  }
  emit('batch-download', indices)
  selectedTaskIds.clear()
}

// 删除某行前先退出重命名编辑态（列表删除会使后面的行索引前移，编辑态不退出会错位到相邻行）
function handleDeleteClick(globalIndex) {
  cancelRename()
  emit('delete', globalIndex)
}

// 列表整体重新加载（弹框重开刷新，父组件给list换新数组）时清空勾选与重命名编辑态
watch(() => props.list, () => {
  selectedTaskIds.clear()
  cancelRename()
})

// 弹框关闭时也清一次：兜住"关闭前正勾着选、下次打开若列表没变化"的残留
watch(() => props.visible, v => {
  if (v) {
    currentPage.value = 1
  } else {
    selectedTaskIds.clear()
    cancelRename()
  }
})
</script>
