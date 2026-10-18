<template>
  <div class="itp-action-bar">
    <div class="itp-action-center" v-if="previewUrl || canBatchClean">
      <!-- 图片导航 -->
      <div class="itp-nav-group" v-if="siblingImages.length > 1">
        <button class="itp-nav-btn" :disabled="!canGoPrev" @click="$emit('prev-image')" title="上一张">
          <AppIcon name="arrow-left" :size="13" /> 上一张
        </button>
        <span class="itp-nav-info">{{ currentImageIndex + 1 }} / {{ siblingImages.length }}</span>
        <button class="itp-nav-btn" :disabled="!canGoNext" @click="$emit('next-image')" title="下一张">
          <AppIcon name="arrow-right" :size="13" /> 下一张
        </button>
      </div>

      <div class="itp-tool-group">
        <!-- 旋转 -->
        <!-- xuechong 2026-10-11 研发BUG-0073 处理锁定：处理期间（上传/生成PDF/修图/批量）除查看类
             （上一张/下一张切换）外全部禁用，处理完成后自动恢复；停止修图是唯一中断入口保持可用 -->
        <div class="itp-rotate-group" v-if="previewUrl && currentFilePath">
          <button class="itp-rotate-btn" :disabled="isRotating || actionsLocked" @click="$emit('rotate', 'left')" title="左旋转90度"><AppIcon name="rotate-left" :size="13" /> 左旋</button>
          <button class="itp-rotate-btn" :disabled="isRotating || actionsLocked" @click="$emit('rotate', 'right')" title="右旋转90度"><AppIcon name="rotate-right" :size="13" /> 右旋</button>
        </div>

        <!-- 撤销/重做 -->
        <div class="itp-history-group">
          <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
               禁用态悬停显示原因；xuechong 2026-10-11 研发BUG-0073 处理锁定：处理中悬停
               提示与"无可撤销"区分开，避免误导 -->
          <button class="itp-history-btn" :disabled="!canUndo || actionsLocked" @click="$emit('undo')" :title="actionsLocked ? '正在处理中，请稍候' : (canUndo ? '撤销' : '暂无可撤销的修改')"><AppIcon name="undo" :size="13" /> 上一步</button>
          <button class="itp-history-btn" :disabled="!canRedo || actionsLocked" @click="$emit('redo')" :title="actionsLocked ? '正在处理中，请稍候' : (canRedo ? '重做' : '暂无可重做的操作')"><AppIcon name="redo" :size="13" /> 下一步</button>
        </div>

        <!-- 图片重绘下拉 -->
        <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
             悬停展开保持产品原有交互不变（用户确认预期行为）；菜单项点击后收起并抛事件 -->
        <div class="itp-dropdown" @mouseenter="!actionsLocked && (openDropdown = 'redraw')" @mouseleave="openDropdown = null">
          <button class="itp-tool-btn itp-btn-orange" :disabled="actionsLocked" title="图片重绘"><AppIcon name="edit" :size="14" /> 图片重绘 <AppIcon name="chevron-down" :size="13" /></button>
          <div class="itp-dropdown-menu" v-show="openDropdown === 'redraw'">
            <div class="itp-dropdown-item" @click="emitAndClose('redraw-enhance')"><AppIcon name="chevrons-up" :size="14" /> 强化</div>
            <div class="itp-dropdown-item" @click="emitAndClose('redraw-weaken')"><AppIcon name="chevrons-down" :size="14" /> 弱化</div>
            <div class="itp-dropdown-divider"></div>
            <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
                 菜单与工具栏 emoji 图标换单色线性 SVG；2026-10-10 用户复验：文本符号↺↻↶↷▾▓░也全部换为AppIcon（图标在左） -->
            <div class="itp-dropdown-item" @click="emitAndClose('redraw-enhance-batch')"><AppIcon name="chevrons-up" :size="14" /> 批量强化</div>
            <div class="itp-dropdown-item" @click="emitAndClose('redraw-weaken-batch')"><AppIcon name="chevrons-down" :size="14" /> 批量弱化</div>
            <div class="itp-dropdown-divider"></div>
            <div class="itp-dropdown-item" @click="emitAndClose('redraw-settings')"><AppIcon name="settings" :size="14" /> 重绘设置</div>
          </div>
        </div>

        <!-- 一键修图下拉（悬停展开，同上） -->
        <div class="itp-dropdown" @mouseenter="!actionsLocked && (openDropdown = 'auto')" @mouseleave="openDropdown = null">
          <button class="itp-tool-btn itp-btn-orange" :disabled="actionsLocked" title="一键修图"><AppIcon name="zap" :size="14" /> 一键修图 <AppIcon name="chevron-down" :size="13" /></button>
          <div class="itp-dropdown-menu" v-show="openDropdown === 'auto'">
            <div class="itp-dropdown-item" @click="emitAndClose('single-clean')"><AppIcon name="edit" :size="14" /> 当前一键修图</div>
            <div class="itp-dropdown-divider"></div>
            <div class="itp-dropdown-item" @click="emitAndClose('batch-clean')"><AppIcon name="fast-forward" :size="14" /> 批量一键修图</div>
            <!-- xuechong 2026-08-26 研发BUG-0032
                 移除"⚙ 一键修图设置"菜单项：全链路无监听无设置界面（半成品），点击零反馈；待设置功能实现后再恢复 -->
          </div>
        </div>

        <!-- xuechong 2026-10-11 研发BUG-0074-图档扫描-3.3.03-图片转PDF模块添加页码选项
             生成页码统一开关（用户复验调整：从左栏移入按钮组）：所有生成链路（手动生成/批量生成/
             修图后自动生成）听此开关，默认勾选；处理锁定期间随工具栏一并禁用；嵌入模式由页面
             控制不渲染（form-in 行为固定：批量链不加页码，组卷环节统一加） -->
        <label class="itp-page-num-check" v-if="showPageToggle" title="生成PDF时在每页底部居中添加页码（从1开始连续编号）">
          <input
            type="checkbox"
            :checked="addPageNumber"
            :disabled="actionsLocked"
            @change="$emit('update:add-page-number', $event.target.checked)"
          />
          <span>添加页码</span>
        </label>

        <!-- xuechong 2026-10-09 研发BUG-0071 两模块按钮语义统一：保存=绿色（对齐编辑PDF"保存修改"），还原=主色橙 -->
        <!-- xuechong 2026-10-11 研发BUG-0073 处理锁定：处理中悬停提示与"无可还原/无修改"区分 -->
        <button class="itp-tool-btn itp-btn-orange" :disabled="!canRestore || actionsLocked" @click="$emit('restore')" :title="actionsLocked ? '正在处理中，请稍候' : (canRestore ? '还原' : '暂无可还原的内容')"><AppIcon name="rotate-left" :size="14" /> 还原</button>
        <button class="itp-tool-btn itp-btn-success" :disabled="!hasEdits || actionsLocked" @click="$emit('save')" :title="actionsLocked ? '正在处理中，请稍候' : (hasEdits ? '保存' : '暂无修改需要保存')"><AppIcon name="save" :size="14" /> 保存</button>
      </div>
    </div>

    <div class="itp-action-right">
      <button
        v-if="isBatchCleaning"
        class="itp-tool-btn itp-stop-btn"
        @click="$emit('stop-batch-clean')"
        title="停止批量修图"
      ><AppIcon name="stop" :size="14" /> 停止修图</button>
      <slot name="right-actions"></slot>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
// xuechong 2026-10-09 研发BUG-0071 工具栏图标：emoji 换单色线性 SVG 图标组件
import AppIcon from './AppIcon.vue'

// xuechong 2026-10-11 研发BUG-0073 处理锁定：本组件新增 actionsLocked（defineProps 需赋值供脚本读取）
const props = defineProps({
  previewUrl: String,
  currentFilePath: String,
  siblingImages: Array,
  currentImageIndex: Number,
  canGoPrev: Boolean,
  canGoNext: Boolean,
  canSingleClean: Boolean,
  canBatchClean: Boolean,
  isBatchCleaning: Boolean,
  isRotating: Boolean,
  canUndo: Boolean,
  canRedo: Boolean,
  hasEdits: Boolean,
  canRestore: Boolean,
  // xuechong 2026-10-11 研发BUG-0074-图档扫描-3.3.03 处理锁定：处理期间修改类按钮禁用
  // （由页面传 isBusy——上传/生成PDF/修图/批量全口径；生成PDF期间旋转/保存会改动正被合成的文件）
  actionsLocked: {
    type: Boolean,
    default: false
  },
  // xuechong 2026-10-11 研发BUG-0074-图档扫描-3.3.03 生成页码统一开关（v-model）：
  // 用户复验调整——从左栏移入按钮组（一键修图与还原之间），随工具栏锁定一并禁用
  addPageNumber: {
    type: Boolean,
    default: true
  },
  // 嵌入模式由页面传 false 不渲染（form-in 行为固定）
  showPageToggle: {
    type: Boolean,
    default: true
  }
})

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 下拉保持原有悬停展开交互；点菜单项先收起再抛事件，确保选择后菜单不残留
const emit = defineEmits([
  'prev-image', 'next-image', 'rotate', 'single-clean', 'batch-clean',
  'undo', 'redo', 'save', 'restore',
  'redraw-enhance', 'redraw-weaken', 'redraw-enhance-batch', 'redraw-weaken-batch', 'redraw-settings',
  'stop-batch-clean',
  'update:add-page-number'  // xuechong 2026-10-11 研发BUG-0074 页码开关 v-model
])

const openDropdown = ref(null)

// xuechong 2026-10-11 研发BUG-0073 修图锁定：锁定期间菜单项点击一律拦截
// （兜底"忙碌开始前菜单已展开"的窗口期，与按钮 disabled、悬停守卫三重保险）
function emitAndClose(name) {
  if (props.actionsLocked) return
  openDropdown.value = null
  emit(name)
}
</script>
