<template>
  <div class="edit-pdf-page">
    <!-- 页面初始化Loading（keep-alive缓存恢复时显示，完全遮挡旧内容） -->
    <div v-if="!pageReady" class="edit-pdf-init-loading">
      <div class="global-loading-spinner"></div>
      <div class="global-loading-text">正在加载...</div>
    </div>

    <!-- 全局Loading遮罩（操作中的loading） -->
    <div v-if="pageReady && globalLoading" class="global-loading-overlay">
      <div class="global-loading-content">
        <div class="global-loading-spinner"></div>
        <div class="global-loading-text">{{ globalLoadingText }}</div>
      </div>
    </div>

    <!-- 顶部导航 -->
    <template v-if="pageReady">
    <div class="itp-header">
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：左上角补系统logo图标+版本号（复用首页顶栏同款结构样式） -->
      <div class="logo-container">
        <img class="logo-icon" src="../assets/logo-white.png" alt="Logo" />
        <div class="title-text">
          <h1>编辑PDF</h1>
          <span class="version">V3.4.00</span>
        </div>
      </div>
      <div class="header-actions">
        <!-- zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化 -->
        <!-- 原「去除空白页/PDF瘦身/添加页码」三个下载时开关整体移除：处理选项移入
             「一键处理」配置弹窗并保存为文件的处理配方（长期生效），下载只取构建结果 -->
        <!-- zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 -->
        <!-- 下载按钮按勾选集合分流：≤1个走原单文件下载（零回归），≥2个批量下载ZIP；0勾选禁用 -->
        <button
          class="itp-back-btn"
          @click="editPdfDownload"
          :disabled="!editPdfCurrentFileInfo || editPdfCheckedCount === 0 || editPdfBatchCleaning"
          :title="editPdfCheckedCount >= 2 ? `批量下载已勾选的 ${editPdfCheckedCount} 个PDF（ZIP打包）` : '下载处理完成后的PDF（未设置配方且无修改时下载原件/当前合并结果）'"
        ><!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 本页emoji图标的emoji换单色线性SVG -->
         <AppIcon name="download" /> {{ editPdfCheckedCount >= 2 ? `下载PDF(${editPdfCheckedCount}个)` : '下载PDF' }}</button>
        <button class="itp-back-btn" @click="editPdfShowHistory" title="查看操作记录"><AppIcon name="clipboard" /> 操作记录</button>
        <HeaderActions />
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：用户徽章与返回按钮互换（返回收尾最右） -->
        <UserBadge :show-logout="false" />
        <button class="itp-back-btn" @click="handleBack"><AppIcon name="arrow-left" :size="13" /> {{ editPdfSource === 'img-to-pdf' ? '返回图转PDF' : '返回首页' }}</button>
      </div>
    </div>

    <div class="main-content-body">
      <div class="main-container">
        <!-- 左侧面板 -->
        <aside class="sidebar">
          <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：上传下拉保持在左栏顶部（原布局即正确，
               图片转PDF已向本布局对齐），两个隐藏input原样保留（webkitdirectory 静态写在标签上） -->
          <div class="upload-section">
            <div class="itp-upload-dropdown" ref="editPdfUploadDropdown" @mouseenter="editPdfUploadMenu = !editPdfBusy ? true : false" @mouseleave="editPdfUploadMenu = false">
              <button type="button" class="itp-upload-label" :class="{ disabled: editPdfBusy }" :disabled="editPdfBusy">
                <AppIcon name="upload" /><span>上传</span><AppIcon name="chevron-down" :size="12" class="itp-upload-caret" />
              </button>
              <div v-if="editPdfUploadMenu" class="itp-upload-menu">
                <button type="button" class="itp-upload-menu-item" @click="pickEditPdfFiles"><AppIcon name="file-text" /> 上传PDF</button>
                <button type="button" class="itp-upload-menu-item" @click="pickEditPdfFolder"><AppIcon name="folder" /> 上传文件夹</button>
              </div>
              <input
                type="file"
                ref="editPdfFolderInput"
                webkitdirectory
                directory
                multiple
                style="display: none;"
                @change="handleEditPdfFolderUpload"
              />
              <input
                type="file"
                ref="editPdfFilesInput"
                accept=".pdf"
                multiple
                style="display: none;"
                @change="handleEditPdfFilesUpload"
              />
            </div>

            <!-- 上传进度条 -->
            <div v-if="editPdfUploadProgress.visible" class="upload-progress">
              <div class="progress-info">
                <span>{{ editPdfUploadProgress.message }}</span>
                <span>{{ editPdfUploadProgress.current }}/{{ editPdfUploadProgress.total }}</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: editPdfUploadProgress.percent + '%' }"></div>
              </div>
            </div>
          </div>

          <!-- 任务信息 -->
          <div v-if="editPdfTaskInfo" class="task-info-card">
            <div class="task-header">
              <span class="folder-icon"><AppIcon name="folder" :size="18" /></span>
              <span class="folder-name">{{ editPdfTaskInfo.folder_name }}</span>
            </div>
            <div class="task-stats">
              <span>共 {{ editPdfTaskInfo.total_files }} 个PDF文件</span>
              <!-- zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 -->
              <!-- 已选计数：批量一键修图/批量下载的作用范围（默认仅第一个文件勾选） -->
              <span>已选 {{ editPdfCheckedCount }} 个</span>
            </div>
          </div>

          <!-- PDF文件列表 -->
          <div class="file-tree-container" v-if="editPdfFileList.length">
            <div class="tree-header">
              <span>PDF文件列表</span>
              <!-- zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 -->
              <!-- 全选/全不选：批量一键修图/批量下载的作用范围（默认仅第一个文件勾选） -->
              <label class="batch-select-all" title="全选/全不选（批量一键处理/批量下载的作用范围）">
                <input
                  type="checkbox"
                  :checked="editPdfAllFilesSelected"
                  :disabled="editPdfBatchCleaning"
                  @change="toggleEditPdfSelectAll"
                />
                <span>全选</span>
              </label>
            </div>
            <div class="pdf-file-list">
              <div
                v-for="(file, index) in editPdfFileList"
                :key="index"
                class="pdf-file-item"
                :class="{ selected: editPdfSelectedFile === index }"
                @click="selectEditPdfFile(index)"
              >
                <!-- zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 -->
                <!-- 批量勾选框：与行点击（切换查看文件）解耦，@click.stop 防止误触发行点击 -->
                <input
                  type="checkbox"
                  class="pdf-file-checkbox"
                  :checked="file.checked"
                  :disabled="editPdfBatchCleaning"
                  @click.stop
                  @change="toggleEditPdfFileChecked(index)"
                  title="勾选加入批量范围（批量一键处理/批量下载）"
                />
                <span class="file-icon"><AppIcon name="file-text" :size="14" /></span>
                <span class="file-name">{{ file.name }}</span>
                <span class="file-pages">{{ file.total_pages }}页</span>
                <span v-if="file.modified" class="modified-badge">已修改</span>
              </div>
            </div>
          </div>

          <!-- 页面缩略图列表 -->
          <div class="file-tree-container" v-if="editPdfPages.length">
            <div class="tree-header">
              <span>页面列表 ({{ editPdfPages.length }}页)</span>
            </div>
            <div class="pdf-page-list">
              <div
                v-for="(page, index) in editPdfPages"
                :key="index"
                class="pdf-page-item"
                :class="{ selected: editPdfCurrentPage === index, 'blank-page-item': editPdfBlankPages.includes(index) }"
                @click="selectEditPdfPage(index)"
              >
                <!-- zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题 -->
                <!-- 原生懒加载：页数多时首屏只请求视口内的缩略图，视口外滚动到再加载
                     （后端按需渲染兜底，未渲页请求到达时当场渲出） -->
                <img :src="page.thumbnail" class="page-thumbnail" loading="lazy" />
                <!-- zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）空白页角标：
                     该页被判为空白页且去空白配方生效，导出时自动去除——消除"列表仍显示=未去除"误导 -->
                <span v-if="editPdfBlankPages.includes(index)" class="blank-page-badge">空白页 · 导出时去除</span>
                <span class="page-number">第 {{ index + 1 }} 页</span>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="!editPdfFileList.length && !editPdfPages.length" class="empty-state">
            <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：空态提示文字按用户要求删除，仅保留图标 -->
            <div class="empty-icon"><AppIcon name="file-text" :size="44" /></div>
          </div>
        </aside>

        <!-- 右侧主内容区 -->
        <main class="main-content">
          <!-- 操作栏 -->
          <div class="action-bar">
            <div class="action-left">
              <span v-if="editPdfCurrentFileInfo" class="selected-path">
                {{ editPdfCurrentFileInfo.name }} - 第 {{ editPdfCurrentPage + 1 }} / {{ editPdfCurrentFileInfo.total_pages }} 页
              </span>
            </div>

            <!-- 中间工具按钮组 -->
            <div class="action-center" v-if="editPdfCurrentPageUrl">
              <!-- 页面切换按钮组 -->
              <div class="nav-btn-group" v-if="editPdfPages.length > 1">
                <button
                  class="nav-btn"
                  :disabled="editPdfCurrentPage <= 0"
                  @click="editPdfGoPrev"
                  title="切换到上一页"
                >
                  <AppIcon name="arrow-left" :size="13" />
                  上一页
                </button>
                <span class="nav-info">{{ editPdfCurrentPage + 1 }} / {{ editPdfPages.length }}</span>
                <button
                  class="nav-btn"
                  :disabled="editPdfCurrentPage >= editPdfPages.length - 1"
                  @click="editPdfGoNext"
                  title="切换到下一页"
                >
                  <AppIcon name="arrow-right" :size="13" />
                  下一页
                </button>
              </div>

              <div class="tool-btn-group">
                <!-- 撤销/重做按钮组 -->
                <div class="history-btn-group">
                  <button
                    class="history-btn prev-btn"
                    :disabled="!editPdfCanUndo"
                    @click="editPdfUndo"
                    title="撤销上一步操作"
                  >
                    <AppIcon name="undo" :size="13" />
                    <span>上一步</span>
                  </button>
                  <button
                    class="history-btn next-btn"
                    :disabled="!editPdfCanRedo"
                    @click="editPdfRedo"
                    title="重做已撤销的操作"
                  >
                    <span>下一步</span>
                    <AppIcon name="redo" :size="13" />
                  </button>
                </div>

                <button
                  class="tool-btn save-btn"
                  :disabled="!editPdfHasChanges"
                  @click="editPdfSave"
                  title="保存当前页面的修改"
                >
                  <span class="tool-icon"><AppIcon name="save" :size="14" /></span>
                  <span>保存修改</span>
                </button>
                <button
                  class="tool-btn restore-btn"
                  :disabled="!editPdfCanRestore"
                  @click="editPdfRestore"
                  title="还原当前页面为原始状态"
                >
                  <span class="tool-icon"><AppIcon name="rotate-left" :size="14" /></span>
                  <span>一键还原</span>
                </button>
                <!-- zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化 -->
                <!-- 「一键修图」升级为「一键处理」：点击先弹出配置弹窗（修图=一次性AI清洁+OCR，
                     其余三项=保存为文件的处理配方长期生效），确认后按勾选集合单文件/批量执行 -->
                <button
                  class="tool-btn clean-btn"
                  :disabled="!editPdfCurrentPageUrl || editPdfBatchCleaning"
                  @click="editPdfOpenProcessDialog"
                  :title="editPdfCheckedCount >= 2 ? `对已勾选的 ${editPdfCheckedCount} 个PDF批量一键处理（可修图+去除空白页+添加页码+PDF瘦身）` : '一键处理：可修图（AI清洁+OCR）并设置去除空白页/添加页码/PDF瘦身（长期生效）'"
                >
                  <span class="tool-icon"><AppIcon name="tool" :size="14" /></span>
                  <span>{{ editPdfBatchCleaning ? '处理中...' : (editPdfCheckedCount >= 2 ? `一键处理(${editPdfCheckedCount}个)` : '一键处理') }}</span>
                </button>
              </div>
            </div>

            <div class="action-right">
            </div>
          </div>

          <!-- 预览区域 - 左右对比布局 -->
          <div class="itp-preview-area" :class="{ 'itp-has-preview': editPdfCurrentPageUrl }">
            <template v-if="editPdfCurrentPageUrl">
              <!-- 左侧原图区 -->
              <div
                class="itp-preview-panel"
                @wheel.prevent="handleEditPdfWheel"
                @mousedown="startEditPdfDrag"
                @mousemove="onEditPdfDrag"
                @mouseup="stopEditPdfDrag"
                @mouseleave="stopEditPdfDrag"
              >
                <div class="itp-preview-title">
                  <span class="itp-title-tag itp-tag-gray">原图区</span>
                </div>
                <div class="itp-preview-content">
                  <div class="image-container" ref="editPdfLeftContainer">
                    <img
                      :src="editPdfOriginalPageUrl || editPdfCurrentPageUrl"
                      :style="editPdfImageStyle"
                      class="preview-image"
                      draggable="false"
                      @error="handleEditPdfOriginalError"
                    />
                  </div>
                  <!-- zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）空白页水印：
                       当前页被判为空白页（去空白配方生效）时预览区同步显示，与左侧列表角标同源同消 -->
                  <div v-if="editPdfBlankPages.includes(editPdfCurrentPage)" class="blank-page-watermark">空白页 · 导出时已去除</div>
                </div>
              </div>

              <!-- 右侧修图区 -->
              <div
                class="itp-preview-panel itp-preview-panel-right itp-editable"
                @wheel.prevent="handleEditPdfWheel"
                @mousedown.prevent="startEditPdfDraw"
                @mousemove="editPdfDraw"
                @mouseup="stopEditPdfDraw"
                @mouseleave="stopEditPdfDrag"
              >
                <div class="itp-preview-title">
                  <span class="itp-title-tag itp-tag-gray">修图区</span>
                </div>
                <div class="itp-preview-content">
                  <div class="image-container" ref="editPdfRightContainer">
                    <img
                      :src="editPdfEditedPageUrl || editPdfCurrentPageUrl"
                      :style="editPdfImageStyle"
                      class="preview-image"
                      draggable="false"
                      ref="editPdfEditedImage"
                    />
                    <!-- 编辑画布层 -->
                    <canvas
                      ref="editPdfCanvas"
                      class="edit-canvas"
                      :style="editPdfCanvasStyle"
                    ></canvas>
                  </div>
                  <!-- 空白页水印（修图区同款，pointer-events:none 不遮挡画笔编辑） -->
                  <div v-if="editPdfBlankPages.includes(editPdfCurrentPage)" class="blank-page-watermark">空白页 · 导出时已去除</div>
                </div>
              </div>
            </template>

            <!-- 空状态 -->
            <div v-else class="itp-scan-placeholder" style="margin: auto;">
              <div class="placeholder-icon"><AppIcon name="file-text" :size="44" /></div>
              <p>选择PDF文件进行编辑</p>
              <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：空态副提示文字按用户要求删除 -->
            </div>
          </div>

          <!-- 一键修图进度条 -->
          <div v-if="showEditPdfCleanProgress" class="process-progress batch-clean-progress">
            <div class="progress-header">
              <span class="progress-title"><AppIcon name="tool" :size="14" /> {{ editPdfCleanProgress.message || '正在处理...' }}</span>
              <div class="progress-stats">
                <span class="current-path"><AppIcon name="file-text" :size="14" /> {{ editPdfCleanProgress.currentPage }}/{{ editPdfCleanProgress.totalPages }} 页</span>
                <span class="process-timer"><AppIcon name="clock" :size="14" /> {{ formatElapsedTime(editPdfCleanElapsed) }}</span>
                <span class="progress-percent">{{ editPdfCleanProgressPercent }}%</span>
                <button
                  v-if="editPdfCleanProgress.status === 'completed' || editPdfCleanProgress.status === 'failed'"
                  class="progress-close-btn"
                  @click="closeEditPdfCleanProgress"
                  title="关闭进度条"
                >✕</button>
              </div>
            </div>
            <div class="progress-bar large">
              <div
                class="progress-fill animated batch-clean"
                :class="{ 'completed': editPdfCleanProgress.status === 'completed', 'failed': editPdfCleanProgress.status === 'failed' }"
                :style="{ width: editPdfCleanProgressPercent + '%' }"
              ></div>
            </div>
          </div>
        </main>
      </div>
    </div>

    <!-- 编辑PDF操作记录弹窗 -->
    <!-- xuechong 2026-10-09 研发BUG-0071 弹框交互统一：浏览类弹框支持点击遮罩关闭（.self 防止点内容误关） -->
    <Transition name="ds-modal">
    <div v-if="showEditPdfHistoryModal" class="itp-history-overlay">
      <div class="itp-history-dialog itp-history-dialog-lg">
        <div class="itp-history-header">
          <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />编辑PDF</h4>
          <button class="itp-history-close" @click="showEditPdfHistoryModal = false" title="关闭操作记录弹窗">&times;</button>
        </div>
        <div class="itp-history-body">
          <div class="itp-history-table-wrap">
            <table class="itp-history-table">
              <thead>
                <tr>
                  <th class="col-index">序号</th>
                  <th>文件名称</th>
                  <!-- zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化 -->
                  <!-- 操作内容列：该PDF执行过的操作（内容类累计+当前配方项），旧记录无该字段显示"—" -->
                  <th>操作内容</th>
                  <th>保存时间</th>
                  <th class="col-dl-count">下载次数</th>
                  <th class="col-action">下载</th>
                  <th class="col-action">预览</th>
                  <th class="col-action">删除</th>
                </tr>
              </thead>
              <tbody>
                <template v-if="editPdfHistoryList.length === 0">
                  <tr>
                    <td colspan="8" style="text-align: center; color: #999; padding: 40px 0;">暂无已编辑的PDF文件</td>
                  </tr>
                </template>
                <template v-else>
                  <tr
                    v-for="(item, idx) in editPdfPaginatedHistory"
                    :key="(editPdfHistoryPage - 1) * editPdfHistoryPageSize + idx"
                    :class="{ 'not-downloaded': (item.download_count || 0) === 0 }"
                  >
                    <td class="index-cell">{{ String((editPdfHistoryPage - 1) * editPdfHistoryPageSize + idx + 1).padStart(3, '0') }}</td>
                    <td class="name-cell" :title="item.filename">{{ item.filename }}</td>
                    <td class="ops-cell" :title="(item.operations || []).join('、') || '—'">{{ (item.operations || []).join('、') || '—' }}</td>
                    <td class="time-cell">{{ item.created_at }}</td>
                    <td class="dl-count-cell">{{ item.download_count || 0 }}</td>
                    <td class="action-cell">
                      <button class="itp-btn itp-btn-success itp-btn-sm" @click="downloadEditPdfHistoryItem(idx, item)" title="下载"><AppIcon name="download" :size="12" /> 下载</button>
                    </td>
                    <td class="action-cell">
                      <button class="itp-btn itp-btn-primary itp-btn-sm" @click="previewEditPdfHistoryItem(idx, item)" title="预览"><AppIcon name="eye" :size="12" /> 预览</button>
                    </td>
                    <td class="action-cell">
                      <button class="itp-btn itp-btn-danger itp-btn-sm" @click="askDeleteEditPdfHistoryItem(idx, item)" title="删除"><AppIcon name="trash" :size="12" /> 删除</button>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="editPdfHistoryList.length > 0" class="itp-history-pagination">
          <button class="page-btn" :disabled="editPdfHistoryPage === 1" @click="editPdfHistoryPage = 1" title="首页">首页</button>
          <button class="page-btn" :disabled="editPdfHistoryPage === 1" @click="editPdfHistoryPage--" title="上一页">上一页</button>
          <span class="page-info">第 {{ editPdfHistoryPage }} / {{ editPdfHistoryTotalPages }} 页</span>
          <button class="page-btn" :disabled="editPdfHistoryPage === editPdfHistoryTotalPages" @click="editPdfHistoryPage++" title="下一页">下一页</button>
          <button class="page-btn" :disabled="editPdfHistoryPage === editPdfHistoryTotalPages" @click="editPdfHistoryPage = editPdfHistoryTotalPages" title="末页">末页</button>
          <select v-model="editPdfHistoryPageSize" class="page-size-select" title="每页显示条数">
            <option :value="10">10条/页</option>
            <option :value="20">20条/页</option>
            <option :value="50">50条/页</option>
          </select>
          <span class="history-total">共 {{ editPdfHistoryList.length }} 条</span>
        </div>
      </div>
    </div>
    </Transition>

    <!-- zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化 -->
    <!-- 一键处理配置弹窗：修图=一次性执行AI清洁+OCR；其余三项长期生效 -->
    <!-- zhaoqiaotong 2026-09-11 GUI复测二轮整改：文案精简去括号；修图与瘦身互斥 -->
    <!-- zhaoqiaotong 2026-09-11 二轮二批整改：已执行项置灰锁定不可取消（已执行的修改不可回退），描述追加"已处理" -->
    <!-- xuechong 2026-10-09 研发BUG-0071 弹框交互统一：一键处理选项弹框点遮罩=取消（等同底部取消按钮） -->
    <Transition name="ds-modal">
    <div v-if="showEditPdfProcessModal" class="itp-history-overlay">
      <div class="itp-history-dialog edit-pdf-process-dialog">
        <div class="itp-history-header">
          <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />一键处理选项</h4>
          <button class="itp-history-close" @click="editPdfCancelProcess" title="关闭一键处理弹窗">&times;</button>
        </div>
        <div class="itp-history-body">
          <div class="process-scope">
            <span class="scope-label">处理范围</span>
            <span class="scope-value">{{ editPdfProcessScopeText }}</span>
          </div>
          <!-- FIX-J 三态：全部已执行=置灰锁定+勾选+"已处理"；部分已执行=可选+"部分已处理"；未执行=可选无标注（均不默认勾选） -->
          <label class="process-option" :class="{ checked: editPdfProcessApplyClean, disabled: editPdfApplyCleanLocked }">
            <input type="checkbox" v-model="editPdfProcessApplyClean" :disabled="editPdfApplyCleanLocked" />
            <span class="option-name">修图</span>
            <span class="option-desc">AI清洁 + OCR文字层{{ editPdfApplyCleanLocked ? '（已处理）' : (editPdfApplyCleanPartial ? '（部分已处理）' : '') }}</span>
          </label>
          <label class="process-option" :class="{ checked: editPdfProcessRemoveBlank, disabled: editPdfRemoveBlankLocked }">
            <input type="checkbox" v-model="editPdfProcessRemoveBlank" :disabled="editPdfRemoveBlankLocked" />
            <span class="option-name">去除空白页</span>
            <span class="option-desc">自动删除空白页，页码连续重编{{ editPdfRemoveBlankLocked ? '（已处理）' : (editPdfRemoveBlankPartial ? '（部分已处理）' : '') }}</span>
          </label>
          <label class="process-option" :class="{ checked: editPdfProcessAddPagenum, disabled: editPdfAddPagenumLocked }">
            <input type="checkbox" v-model="editPdfProcessAddPagenum" :disabled="editPdfAddPagenumLocked" />
            <span class="option-name">添加页码</span>
            <span class="option-desc">每页底部添加页码，已有页码自动重编{{ editPdfAddPagenumLocked ? '（已处理）' : (editPdfAddPagenumPartial ? '（部分已处理）' : '') }}</span>
          </label>
          <label
            class="process-option"
            :class="{ checked: editPdfProcessShrink, disabled: editPdfShrinkMutex || editPdfShrinkLocked }"
            :title="editPdfShrinkMutex ? '修图已包含瘦身' : '减小文件体积，不影响清晰度'"
          >
            <input
              type="checkbox"
              v-model="editPdfProcessShrink"
              :disabled="editPdfShrinkMutex || editPdfShrinkLocked"
            />
            <span class="option-name">PDF瘦身</span>
            <span class="option-desc">{{ editPdfShrinkLocked ? '减小文件体积，不影响清晰度（已处理）' : (editPdfShrinkMutex ? '修图已包含瘦身' : (editPdfShrinkPartial ? '减小文件体积，不影响清晰度（部分已处理）' : '减小文件体积，不影响清晰度')) }}</span>
          </label>
        </div>
        <div class="itp-history-footer">
          <button class="itp-btn itp-btn-primary" @click="editPdfConfirmProcess" :disabled="editPdfProcessSubmitting" title="按以上选项开始处理">
            <AppIcon name="play" :size="13" /> {{ editPdfProcessSubmitting ? '启动中...' : '开始处理' }}
          </button>
          <button class="itp-btn itp-btn-default" @click="editPdfCancelProcess" title="取消不执行任何处理"><AppIcon name="x" :size="13" /> 取消</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：操作记录删除统一站内确认弹框（原浏览器原生confirm） -->
    <Transition name="ds-modal">
    <div v-if="editPdfDeleteConfirm" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />删除记录</h4>
        <p>确定要删除记录“{{ editPdfDeleteConfirm.item.filename }}”吗？删除后不可恢复。</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="editPdfDeleteConfirm = null"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-danger" @click="confirmEditPdfHistoryDelete"><AppIcon name="trash" :size="13" /> 确认删除</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：未保存离开确认弹框（原浏览器原生confirm） -->
    <Transition name="ds-modal">
    <div v-if="editPdfLeaveConfirm" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />未保存的修改</h4>
        <p>当前页面有未保存的修改，确定要离开吗？离开后未保存的修改将丢失。</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="editPdfLeaveConfirm = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-warning" @click="doLeaveEditPdf"><AppIcon name="log-out" :size="13" /> 确定离开</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 -->
    <!-- 本页内联 toast 渲染已移除：统一由 RootLayout 挂载的全局 ToastContainer 渲染（error 持久显示/点击复制/× 关闭） -->
    </template>
  </div>
</template>

<script setup>
defineOptions({ name: 'EditPdfPage' })
// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 错误翻译共享模块
import { translateError } from '../utils/translateError'
import { ref, computed, watch, nextTick, onActivated } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { onUnmounted } from 'vue'
import { usePdfStore } from '../stores/pdf'
import * as api from '../api'
// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// 接入全局 useToast 单例（替换本页私有 toast 实现），渲染统一走 RootLayout 的 ToastContainer
import { useToast } from '../composables/useToast'
import HeaderActions from '../components/HeaderActions.vue'
import UserBadge from '../components/UserBadge.vue'
// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 本页 emoji 图标统一换单色线性 SVG 图标组件
import AppIcon from '../components/AppIcon.vue'

const isDev = import.meta.env.DEV
function devLog(...args) {
  if (!isDev) return
  if (args.length > 0 && ['log', 'error', 'warn', 'info'].includes(args[0])) {
    console[args[0]](...args.slice(1))
  } else {
    console.log(...args)
  }
}

const router = useRouter()
const pdfStore = usePdfStore()

// 记录编辑来源（用于返回按钮导航）
const editPdfSource = ref(null)

// xuechong 2026-10-10 研发BUG-0071 用户复验：返回时的未保存离开确认改站内弹框（原浏览器原生confirm）
const editPdfLeaveConfirm = ref(false)

function handleBack() {
  if (editPdfBusy.value) {
    showToast('正在处理中，请稍候', 'warning')
    return
  }
  if (editPdfHasChanges.value) {
    editPdfLeaveConfirm.value = true
    return
  }
  doLeaveEditPdf()
}

function doLeaveEditPdf() {
  editPdfLeaveConfirm.value = false
  // 停止所有运行中的定时器
  stopEditPdfCleanAll()
  editPdfOcrAllRunning.value = false

  // 清空展示状态并显示loading，确保keep-alive缓存的是空状态而非旧PDF
  const source = editPdfSource.value
  resetEditPdfState()
  pageReady.value = false

  if (source === 'img-to-pdf') {
    router.push('/img-to-pdf')
  } else {
    router.push('/')
  }
}

// ============================================================
// 全局Loading
// ============================================================
// keep-alive 缓存控制：pageReady=false 时只显示loading，防止闪现旧PDF内容
const pageReady = ref(false)

const globalLoading = ref(false)
const globalLoadingText = ref('')

function showGlobalLoading(text = '处理中，请稍候...') {
  globalLoadingText.value = text
  globalLoading.value = true
}

function hideGlobalLoading() {
  globalLoading.value = false
  globalLoadingText.value = ''
}

// ============================================================
// Toast 消息
// ============================================================
// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// 删除本页私有 toasts/showToast（3 秒自动消失的旧机制），统一使用全局 useToast：
// error 提示持久显示、点击文字复制全文、右侧 × 按钮关闭，与图片转PDF模块一致
const { showToast } = useToast()

// ============================================================
// 工具函数
// ============================================================
function formatElapsedTime(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

// ============================================================
// 编辑PDF相关状态
// ============================================================
const editPdfBusy = ref(false)
const editPdfTaskInfo = ref(null)
const editPdfFileList = ref([])
const editPdfSelectedFile = ref(-1)
const editPdfPages = ref([])
const editPdfCurrentPage = ref(0)
const editPdfOriginalPageUrl = ref('')
const editPdfCurrentPageUrl = ref('')
const editPdfEditedPageUrl = ref('')
// zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
// 当前查看文件的内容版本号（后端 process_recipe.json 的 version，内容变化即+1）：
// 页面图片URL的 ?v= 参数来源——内容不变URL不变命中浏览器缓存（替代 ?t=时间戳的
// 每次全量重下），内容变化（保存/还原/修图）URL自动换新。加载时从 pages 接口设置，
// 保存/还原成功后按接口返回更新
const editPdfCurrentVersion = ref(0)
const editPdfHasChanges = ref(false)
const editPdfCanUndo = ref(false)
const editPdfCanRedo = ref(false)
const editPdfCanRestore = ref(false)
const editPdfScale = ref(1)
const editPdfPosition = ref({ x: 0, y: 0 })
const editPdfIsDragging = ref(false)
const editPdfIsDrawing = ref(false)
const editPdfHistory = ref([])
const editPdfHistoryIndex = ref(-1)
const editPdfBrushSize = ref(30)
const editPdfLastDrawPos = ref(null)
const editPdfHasDrawn = ref(false)
const editPdfCanvas = ref(null)
const editPdfEditedImage = ref(null)
const editPdfFolderInput = ref(null)
const editPdfFilesInput = ref(null)
// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 上传入口合并为下拉（对齐图片转PDF FileSidebar 设计）：菜单状态+容器引用+菜单项触发；
// input 的 change 与原上传逻辑零改动，仅打开方式从 label 包裹改为脚本触发 click
const editPdfUploadMenu = ref(false)
const editPdfUploadDropdown = ref(null)

function pickEditPdfFiles() {
  editPdfUploadMenu.value = false
  editPdfFilesInput.value?.click()
}

function pickEditPdfFolder() {
  editPdfUploadMenu.value = false
  editPdfFolderInput.value?.click()
}
const editPdfLeftContainer = ref(null)
const editPdfRightContainer = ref(null)
let editPdfCanvasCtx = null
const showEditPdfHistoryModal = ref(false)
const editPdfHistoryList = ref([])
const editPdfHistoryPage = ref(1)
const editPdfHistoryPageSize = ref(10)
const showEditPdfCleanProgress = ref(false)
const editPdfCleanProgress = ref({
  currentPage: 0,
  totalPages: 0,
  phase: '',
  message: '',
  status: '',
  isDualLayer: false
})
const editPdfCleanElapsed = ref(0)
let editPdfCleanTimer = null
let editPdfCleanPollTimer = null
const editPdfOcrLang = ref('ch')
const editPdfOcrAllRunning = ref(false)
const editPdfUploadProgress = ref({
  visible: false,
  current: 0,
  total: 0,
  percent: 0,
  message: ''
})
// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 「一键处理」配置弹窗状态：修图=一次性执行AI清洁+OCR（apply_clean）；其余三项=
// 写入文件的处理配方（长期生效，由后端统一构建自动应用）。原顶部三个下载时开关
// （editPdfAddPageNumber/editPdfShrink/editPdfRemoveBlankPages，任务级）整体移除
const showEditPdfProcessModal = ref(false)
const editPdfProcessApplyClean = ref(true)
const editPdfProcessRemoveBlank = ref(false)
const editPdfProcessAddPagenum = ref(false)
const editPdfProcessShrink = ref(false)
const editPdfProcessSubmitting = ref(false)
// zhaoqiaotong 2026-09-11 研发需求-0167 四轮整改（FIX-I）批量混合状态三态化：
// 弹窗打开时缓存全部目标文件状态（cleaned/配方），选项按"未执行/部分已执行/全部已执行"
// 三态渲染——任一成员已执行的项=保持勾选+置灰（不可回退原则），但批量执行时逐文件
// 跳过已执行成员并给未执行成员新增（用户确认的方案B）；全部已执行的项同二批锁定语义
const editPdfProcessStates = ref([])
const _cleanSome = computed(() => editPdfProcessStates.value.some(s => s.cleaned))
const _cleanAll = computed(() => editPdfProcessStates.value.length > 0 && editPdfProcessStates.value.every(s => s.cleaned))
const _recipeSome = (key) => editPdfProcessStates.value.some(s => s.recipe && !!s.recipe[key])
const _recipeAll = (key) => editPdfProcessStates.value.length > 0 && editPdfProcessStates.value.every(s => s.recipe && !!s.recipe[key])
// 弹窗"处理范围"文案：批量显示勾选数与统一应用说明，单文件显示勾选文件名
// （FIX-K2：处理对象=勾选集合，与当前查看文件无关）
const editPdfProcessScopeText = computed(() => {
  const checked = editPdfCheckedFiles.value
  if (checked.length >= 2) {
    return `已勾选的 ${checked.length} 个PDF（以上选项统一应用到全部勾选文件）`
  }
  return checked.length === 1 ? `「${checked[0].name}」` : ''
})
// 修图锁定/部分：修图是动作非配方——部分已修→默认勾选**可选**（取消只是不给未修成员修，
// 不回退已修效果）；全部已修→不勾+置灰"已处理"。执行时已修成员自动跳过
const editPdfApplyCleanLocked = computed(() => _cleanAll.value)
const editPdfApplyCleanPartial = computed(() => _cleanSome.value && !_cleanAll.value)
// 配方项锁定/部分：任一成员已生效→保持勾选+置灰（取消会回退该成员效果，违反不可回退原则）
const editPdfRemoveBlankLocked = computed(() => _recipeAll('remove_blank_pages'))
const editPdfRemoveBlankPartial = computed(() => _recipeSome('remove_blank_pages') && !_recipeAll('remove_blank_pages'))
const editPdfAddPagenumLocked = computed(() => _recipeAll('add_page_number'))
const editPdfAddPagenumPartial = computed(() => _recipeSome('add_page_number') && !_recipeAll('add_page_number'))
const editPdfShrinkLocked = computed(() => _cleanAll.value || _recipeAll('shrink'))
const editPdfShrinkPartial = computed(() => !_cleanAll.value && !_recipeAll('shrink') && _recipeSome('shrink'))
// 瘦身互斥置灰态：勾选修图即置灰（FIX-J修复：去掉"部分成员已瘦身不互斥"的过时保护——
// 执行层只增不减后，取消/置灰瘦身勾选不会回退已生效成员的瘦身，互斥可无条件生效）
const editPdfShrinkMutex = computed(() => editPdfProcessApplyClean.value && !editPdfShrinkLocked.value)

// zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改 修图与PDF瘦身互斥：
// 勾选修图时瘦身自动取消并置灰——已执行成员的瘦身效果由执行层"只增不减"并集保护
watch(editPdfProcessApplyClean, (checked) => {
  if (checked) {
    editPdfProcessShrink.value = false
  }
})

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 批量一键修图进行中标志：期间禁用勾选/全选/修图/下载并阻断返回导航
const editPdfBatchCleaning = ref(false)

// zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）当前查看文件的空白页判定列表
// （0基原始页索引，去空白配方激活时由后端缓存判定）：页面列表对应缩略图显示
// "空白页·导出时已去除"角标，消除"列表仍显示空白页=未去除"的误导；编辑该页后
// 判定缓存失效，角标随下次处理/查询自动消失（标记不删除列表项，页号寻址不受影响）
const editPdfBlankPages = ref([])

// ============================================================
// 编辑PDF计算属性
// ============================================================
const editPdfCleanProgressPercent = computed(() => {
  const { currentPage, totalPages, phase } = editPdfCleanProgress.value
  if (!totalPages || totalPages === 0) return 0

  const pageProgress = (currentPage - 1) / totalPages
  const currentStepProgress = phase === 'cleaning' ? 0.5 : 1

  if (phase === 'done') {
    return 100
  }

  const totalProgress = (pageProgress + currentStepProgress / totalPages) * 100
  return Math.round(Math.min(99, totalProgress))
})

const editPdfHistoryTotalPages = computed(() => {
  return Math.max(1, Math.ceil(editPdfHistoryList.value.length / editPdfHistoryPageSize.value))
})

const editPdfPaginatedHistory = computed(() => {
  const start = (editPdfHistoryPage.value - 1) * editPdfHistoryPageSize.value
  const end = start + editPdfHistoryPageSize.value
  return editPdfHistoryList.value.slice(start, end)
})

watch(editPdfHistoryPageSize, () => {
  editPdfHistoryPage.value = 1
})

const editPdfCurrentFileInfo = computed(() => {
  if (editPdfSelectedFile.value >= 0 && editPdfSelectedFile.value < editPdfFileList.value.length) {
    return editPdfFileList.value[editPdfSelectedFile.value]
  }
  return null
})

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 勾选相关计算属性：已勾选文件清单/计数（批量一键修图/批量下载的作用范围）
// 与全选状态（列表头全选复选框的显示状态）
const editPdfCheckedFiles = computed(() => editPdfFileList.value.filter(f => f.checked))
const editPdfCheckedCount = computed(() => editPdfCheckedFiles.value.length)
const editPdfAllFilesSelected = computed(() =>
  editPdfFileList.value.length > 0 && editPdfCheckedCount.value === editPdfFileList.value.length
)

const editPdfImageStyle = computed(() => ({
  transform: `scale(${editPdfScale.value}) translate(${editPdfPosition.value.x}px, ${editPdfPosition.value.y}px)`,
  transformOrigin: 'center center'
}))

const editPdfCanvasStyle = computed(() => ({
  transform: `translate(-50%, -50%) scale(${editPdfScale.value}) translate(${editPdfPosition.value.x}px, ${editPdfPosition.value.y}px)`,
  transformOrigin: 'center center'
}))

// ============================================================
// 编辑PDF相关方法
// ============================================================

// zhaoqiaotong 2026-09-02 研发BUG-0040-图档扫描-3.2.03-编辑PDF模块若干问题修复
// 前端预检查单文件大小上限（与后端 edit_pdf.py 的 max_pdf_bytes 保持一致）：
// 后端校验发生在整个请求体传输并落盘之后，超大文件会白等完整上传才报错，
// 因此在点击上传选定文件时立即用 file.size 判断，超限直接提示并终止，不发请求
const EDIT_PDF_MAX_FILE_SIZE = 1024 * 1024 * 1024  // 1GB

// 上传前大小预检查：存在超限文件时 toast 提示并返回 false（调用方终止上传）
function checkEditPdfFileSize(pdfFiles) {
  const oversize = pdfFiles.filter(f => f.size > EDIT_PDF_MAX_FILE_SIZE)
  if (oversize.length === 0) return true
  const names = oversize.slice(0, 3).map(f => f.name).join('、')
  const suffix = oversize.length > 3 ? ` 等 ${oversize.length} 个文件` : ''
  showToast(`PDF文件 (${names}${suffix}) 超过大小限制 (1GB)，已终止上传`, 'error')
  return false
}

// zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
// 与图片转PDF模块一致：所选文件混入非PDF时用 error 持久警告条明示忽略明细（原先静默过滤用户无感知）；
// 扩展名收集规则含"无扩展名"兜底，文案风格对齐 useImageToPdf.js 的非图片忽略提示
function notifyIgnoredNonPdf(allFiles, pdfFiles) {
  const ignoredCount = allFiles.length - pdfFiles.length
  if (ignoredCount <= 0) {
    return
  }
  const ignoredExts = new Set()
  for (const f of allFiles) {
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      const dot = f.name.lastIndexOf('.')
      ignoredExts.add(dot >= 0 ? f.name.slice(dot).toLowerCase() : '无扩展名')
    }
  }
  showToast(`已忽略 ${ignoredCount} 个非PDF文件（${Array.from(ignoredExts).join('、')}），仅上传PDF格式`, 'error')
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 切换单个文件的批量勾选状态（勾选与查看文件解耦，仅影响批量操作范围）
function toggleEditPdfFileChecked(index) {
  const file = editPdfFileList.value[index]
  if (!file) return
  file.checked = !file.checked
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 列表头全选/全不选：当前非全选→全选，已全选→全不选
function toggleEditPdfSelectAll() {
  const target = !editPdfAllFilesSelected.value
  editPdfFileList.value.forEach(f => { f.checked = target })
}

// 处理编辑PDF文件夹上传
async function handleEditPdfFolderUpload(event) {
  const files = event.target.files
  if (!files || files.length === 0) return

  // zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
  // 文件夹混入非PDF文件时持久提示忽略明细
  const allFiles = Array.from(files)
  const pdfFiles = allFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'))
  notifyIgnoredNonPdf(allFiles, pdfFiles)

  if (pdfFiles.length === 0) {
    showToast('所选文件夹中没有PDF文件', 'warning')
    event.target.value = ''
    return
  }

  // zhaoqiaotong 2026-09-02 研发BUG-0040-图档扫描-3.2.03-编辑PDF模块若干问题修复
  // 发请求前预检查大小，超限立即提示并终止
  if (!checkEditPdfFileSize(pdfFiles)) {
    event.target.value = ''
    return
  }

  await uploadEditPdfFiles(pdfFiles, true)
  event.target.value = ''
}

// 处理编辑PDF多文件上传
async function handleEditPdfFilesUpload(event) {
  const files = event.target.files
  if (!files || files.length === 0) return

  // zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能
  // 多选文件混入非PDF文件时同样持久提示忽略明细（用户要求与文件夹入口一致）
  const allFiles = Array.from(files)
  const pdfFiles = allFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'))
  notifyIgnoredNonPdf(allFiles, pdfFiles)

  if (pdfFiles.length === 0) {
    showToast('请选择PDF文件', 'warning')
    event.target.value = ''
    return
  }

  // zhaoqiaotong 2026-09-02 研发BUG-0040-图档扫描-3.2.03-编辑PDF模块若干问题修复
  // 发请求前预检查大小，超限立即提示并终止
  if (!checkEditPdfFileSize(pdfFiles)) {
    event.target.value = ''
    return
  }

  await uploadEditPdfFiles(pdfFiles, false)
  event.target.value = ''
}

// 上传编辑PDF文件（通用方法）
async function uploadEditPdfFiles(pdfFiles, isFolder) {
  devLog('[编辑PDF] 开始上传', pdfFiles.length, '个PDF文件')

  editPdfBusy.value = true
  editPdfUploadProgress.value = {
    visible: true,
    current: 0,
    total: pdfFiles.length,
    percent: 0,
    message: '正在上传...'
  }
  showGlobalLoading('正在上传PDF文件...')

  try {
    const formData = new FormData()
    pdfFiles.forEach(file => {
      formData.append('files', file, file.webkitRelativePath || file.name)
    })

    const response = await api.uploadEditPdfMultiple(formData)
    const data = response.data

    if (data.success) {
      editPdfTaskInfo.value = {
        task_id: data.task_id,
        folder_name: data.folder_name || '上传的PDF',
        total_files: data.files.length
      }

      // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 新上传文件：静默清除上一轮一键处理完成横幅（提示针对旧任务已过期）
      dismissEditPdfCleanProgressBanner()
      // zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
      // 文件列表项新增 cleaned 标志（前端跟踪是否已修图，供一键处理弹窗智能默认：
      // 已修图过的文件默认不勾修图）；原三开关复位逻辑随开关一并移除（配方为文件级
      // 设置存于后端，新任务自然无配方）
      editPdfFileList.value = data.files.map((file, idx) => ({
        name: file.filename,
        path: file.path,
        total_pages: file.total_pages,
        task_id: data.task_id,
        file_id: file.file_id,
        modified: false,
        cleaned: false,
        // zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
        // 默认仅勾选第一个文件：默认不执行批量操作（需求红线），按钮保持单文件行为
        checked: idx === 0
      }))

      // 默认选中第一个文件
      // zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 加 await：首文件页面加载完成前不让本函数的 finally 执行——其 hideGlobalLoading
      // 会把 selectEditPdfFile 自己显示的"正在加载PDF页面"遮罩提前关掉（全局loading是
      // 非计数布尔开关），导致上传后首文件加载期间界面无任何加载指示
      if (editPdfFileList.value.length > 0) {
        await selectEditPdfFile(0)
      }

      showToast(`成功加载 ${data.files.length} 个PDF文件`, 'success')
    } else {
      showToast(data.message || data.detail || '上传失败', 'error')
    }
  } catch (error) {
    devLog('error', '[编辑PDF] 上传失败:', error)
    showToast(translateError(error, '上传失败: '), 'error')
  } finally {
    editPdfBusy.value = false
    editPdfUploadProgress.value.visible = false
    hideGlobalLoading()
  }
}

// 选择编辑PDF文件
async function selectEditPdfFile(index) {
  if (index < 0 || index >= editPdfFileList.value.length) return

  editPdfSelectedFile.value = index
  const file = editPdfFileList.value[index]

  editPdfBusy.value = true
  showGlobalLoading('正在加载PDF页面...')
  try {
    // zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    // 页面列表与空白页配方两请求并行（原串行两连发，遮罩时长多付一个完整往返）；
    // 配方查询失败降级为无标记（角标是增强显示不影响功能），不阻断页面列表加载
    const [response, recipeRes] = await Promise.all([
      api.getEditPdfFilePages(file.task_id, file.file_id),
      api.getEditPdfProcessRecipe(file.task_id, file.file_id).catch(err => {
        devLog('error', '[编辑PDF] 空白页判定查询失败，按无标记显示:', err)
        return null
      })
    ])
    const data = response.data

    if (data.success) {
      // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 内容版本号（服务器权威）+ 版本化URL：内容不变URL不变命中浏览器缓存——切回看过的
      // 文件零图片请求（原 ?t=时间戳每次切换全量重下，是图片请求风暴与护航效应的源头）
      const version = (data.version !== undefined && data.version !== null) ? data.version : 0
      editPdfCurrentVersion.value = version
      editPdfPages.value = data.pages.map((page, i) => ({
        thumbnail: `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${i}/thumbnail?v=${version}`,
        original: `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${i}/original?v=${version}`,
        // zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 后端每页返回 edited 标志：
        // 切换文件后重新加载页面列表时正确显示已保存的手工编辑（修复显示回退为原图的存量缺陷）；
        // modified 同步置位（还原按钮依据）
        edited: page.edited ? `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${i}/edited?v=${version}` : null,
        modified: !!page.edited
      }))

      // zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）顺带拉取该文件空白页判定
      // （去空白配方激活时后端返回0基页索引列表），页面列表对应缩略图显示角标；
      // 查询失败按无标记处理（角标是增强显示，不影响功能）
      editPdfBlankPages.value = (recipeRes && recipeRes.data && recipeRes.data.blank_pages) || []

      if (editPdfPages.value.length > 0) {
        selectEditPdfPage(0)
      }
    }
  } catch (error) {
    devLog('error', '[编辑PDF] 加载页面失败:', error)
    showToast('加载页面失败', 'error')
  } finally {
    editPdfBusy.value = false
    hideGlobalLoading()
  }
}

// 选择编辑PDF页面
function selectEditPdfPage(index) {
  if (index < 0 || index >= editPdfPages.value.length) return

  editPdfCurrentPage.value = index
  const page = editPdfPages.value[index]
  const file = editPdfCurrentFileInfo.value

  if (file) {
    // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    // backup URL 按内容版本号寻址：未修图页与修图区同内容同URL命中缓存（修图生成
    // 备份时version+1自动换新）——切页不再每页重下3.4MB（原图区卡顿主因之一）
    editPdfOriginalPageUrl.value = `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${index}/backup?v=${editPdfCurrentVersion.value}`
  }
  editPdfCurrentPageUrl.value = page.original
  editPdfEditedPageUrl.value = page.edited || page.original
  editPdfCanRestore.value = page.modified

  // zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
  // 翻页预取：后台预加载下一页原图（new Image 触发浏览器请求；未渲页由后端按需渲染
  // 当场渲出并落盘），正常翻到下一页时直接命中，消除单页首次查看的渲染等待
  const nextPage = editPdfPages.value[index + 1]
  if (nextPage && nextPage.original) {
    const preloadImg = new Image()
    preloadImg.src = nextPage.original
  }

  // zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 保存按钮只由"画布有未保存
  // 的新修改"驱动（画笔落笔置位），不再把"该页历史上被修改过"当作未保存修改——
  // 修复"保存后切页再切回保存按钮又可点"的存量缺陷（重复提交同样内容）
  editPdfHasChanges.value = false

  editPdfScale.value = 1
  editPdfPosition.value = { x: 0, y: 0 }

  editPdfCanvasCtx = null
  editPdfHistory.value = []
  editPdfHistoryIndex.value = -1
  editPdfCanUndo.value = false
  editPdfCanRedo.value = false

  nextTick(() => {
    setTimeout(() => {
      initEditPdfCanvas()
    }, 100)
  })
}

function editPdfGoPrev() {
  if (editPdfCurrentPage.value > 0) {
    selectEditPdfPage(editPdfCurrentPage.value - 1)
  }
}

function editPdfGoNext() {
  if (editPdfCurrentPage.value < editPdfPages.value.length - 1) {
    selectEditPdfPage(editPdfCurrentPage.value + 1)
  }
}

function editPdfUndo() {
  if (!editPdfCanUndo.value || !editPdfCanvasCtx || !editPdfCanvas.value) return

  editPdfHistoryIndex.value--
  const imageData = editPdfHistory.value[editPdfHistoryIndex.value]
  editPdfCanvasCtx.putImageData(imageData, 0, 0)

  editPdfCanUndo.value = editPdfHistoryIndex.value > 0
  editPdfCanRedo.value = true

  devLog('[编辑PDF] 撤销，当前索引:', editPdfHistoryIndex.value)
}

function editPdfRedo() {
  if (!editPdfCanRedo.value || !editPdfCanvasCtx || !editPdfCanvas.value) return

  editPdfHistoryIndex.value++
  const imageData = editPdfHistory.value[editPdfHistoryIndex.value]
  editPdfCanvasCtx.putImageData(imageData, 0, 0)

  editPdfCanUndo.value = true
  editPdfCanRedo.value = editPdfHistoryIndex.value < editPdfHistory.value.length - 1

  devLog('[编辑PDF] 重做，当前索引:', editPdfHistoryIndex.value)
}

// 保存修改
async function editPdfSave() {
  if (!editPdfCurrentFileInfo.value || !editPdfCanvasCtx || !editPdfCanvas.value) {
    showToast('没有可保存的修改', 'warning')
    return
  }

  const file = editPdfCurrentFileInfo.value
  const pageIndex = editPdfCurrentPage.value

  // zhaoqiaotong 2026-09-12 研发需求-0167 七轮整改（FIX-L2）空白删除页保存拦截：
  // 该页导出时将被自动移除，编辑（涂白）无意义——提示后自动作废画布修改并复位
  // 未保存标志（解死锁：否则"请先保存"与"修改无效"互相拦截，下载/处理被卡死）
  if (editPdfBlankPages.value.includes(pageIndex)) {
    showToast('该页为空白删除页，修改无效（导出时将自动去除）', 'warning')
    if (editPdfHistory.value.length > 0) {
      editPdfHistoryIndex.value = 0
      editPdfCanvasCtx.putImageData(editPdfHistory.value[0], 0, 0)
      editPdfCanUndo.value = false
      editPdfCanRedo.value = editPdfHistory.value.length > 1
    }
    editPdfHasChanges.value = false
    editPdfHasDrawn.value = false
    return
  }

  editPdfBusy.value = true
  showGlobalLoading('正在保存并重建文字层，请稍候...')

  try {
    const canvas = editPdfCanvas.value
    const imageData = canvas.toDataURL('image/jpeg', 0.85)

    const response = await api.saveEditPdfPage({
      task_id: file.task_id,
      file_id: file.file_id,
      page_num: pageIndex,
      image_data: imageData,
      ocr_lang: editPdfOcrLang.value
    })

    const data = response.data

    if (data.success) {
      // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // edited URL 按保存返回的新内容版本号寻址（每次保存内容变URL变，其余页URL不变
      // 命中缓存）；同步更新当前版本号
      const newVersion = (data.version !== undefined && data.version !== null) ? data.version : editPdfCurrentVersion.value
      editPdfCurrentVersion.value = newVersion
      if (editPdfPages.value[pageIndex]) {
        editPdfPages.value[pageIndex].modified = true
        editPdfPages.value[pageIndex].edited = data.edited_url + '?v=' + newVersion
      }

      if (editPdfFileList.value[editPdfSelectedFile.value]) {
        editPdfFileList.value[editPdfSelectedFile.value].modified = true
      }

      editPdfHasChanges.value = false
      // FIX-L2：空白页保存已在入口拦截，正常页保存不影响空白页角标（乐观移除逻辑已删）
      showToast(`保存成功，已识别 ${data.text_count || 0} 个文字块`, 'success')
    } else {
      showToast(data.message || '保存失败', 'error')
    }
  } catch (error) {
    devLog('error', '[编辑PDF] 保存失败:', error)
    showToast(translateError(error, '保存失败: '), 'error')
  } finally {
    editPdfBusy.value = false
    hideGlobalLoading()
  }
}

// 还原
// zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 已保存的手工编辑必须走服务端
// 还原（原纯前端画布回退不触达服务端，下载与操作记录中的PDF不会复原且界面与实际
// 不一致）：修图过的页回到修图后状态，未修图过的页回到原始页；未保存的画笔操作
// 仍走本地画布回退
async function editPdfRestore() {
  if (!editPdfCurrentFileInfo.value) return

  const file = editPdfCurrentFileInfo.value
  const pageIndex = editPdfCurrentPage.value
  const page = editPdfPages.value[pageIndex]
  if (!page) return

  if (page.modified) {
    editPdfBusy.value = true
    showGlobalLoading('正在还原页面...')
    try {
      const response = await api.restoreEditPdfPage({
        task_id: file.task_id,
        file_id: file.file_id,
        page_num: pageIndex,
        ocr_lang: editPdfOcrLang.value
      })
      if (!response.data.success) {
        showToast(response.data.message || '还原失败', 'error')
        return
      }
      // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 记录还原后的内容版本号（还原分支为bump后新值，幂等分支为当前值），下方重建URL使用
      if (response.data.version !== undefined && response.data.version !== null) {
        editPdfCurrentVersion.value = response.data.version
      }
    } catch (error) {
      devLog('error', '[编辑PDF] 还原失败:', error)
      showToast(translateError(error, '还原失败: '), 'error')
      return
    } finally {
      editPdfBusy.value = false
      hideGlobalLoading()
    }
  }

  // 画布本地回退（未保存的画笔操作撤销到首帧）
  if (editPdfHistory.value.length > 0 && editPdfCanvasCtx && editPdfCanvas.value) {
    editPdfHistoryIndex.value = 0
    const imageData = editPdfHistory.value[0]
    editPdfCanvasCtx.putImageData(imageData, 0, 0)

    editPdfCanUndo.value = false
    editPdfCanRedo.value = editPdfHistory.value.length > 1
  }

  // 刷新该页图片URL（服务端页面产物已变化，按新内容版本号破缓存）并复位状态
  page.edited = null
  page.modified = false
  page.original = `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${pageIndex}/original?v=${editPdfCurrentVersion.value}`
  editPdfCurrentPageUrl.value = page.original
  editPdfEditedPageUrl.value = page.original
  editPdfHasChanges.value = false
  editPdfCanRestore.value = false
  setTimeout(() => {
    initEditPdfCanvas()
  }, 100)
  // FIX-L2：空白页保存已被拦截（不存在已保存编辑），还原则该页必非空白页，
  // 角标不受影响（乐观移除逻辑已删，所见与所下载一致）
  showToast('已还原', 'success')
}

// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 「一键处理」入口（原「一键修图」演进）：点击先弹配置弹窗——修图=一次性执行AI清洁+OCR；
// 去除空白页/添加页码/PDF瘦身=长期生效
// zhaoqiaotong 2026-09-11 四轮整改（FIX-I）批量混合状态：逐文件查询全部目标状态并缓存
// （editPdfProcessStates），选项按三态渲染（未执行/部分已执行/全部已执行），确认时
// 逐文件比对跳过已执行成员——批量勾选含"已执行"与"未执行"成员时不再误锁
async function editPdfOpenProcessDialog() {
  if (!editPdfCurrentFileInfo.value) {
    showToast('请先选择PDF文件', 'warning')
    return
  }

  // zhaoqiaotong 2026-09-12 六轮整改（FIX-K2）勾选=处理对象（点击行仅浏览）：
  // 0勾选提示选择；目标集合=勾选集合（1个或多个，不再回退当前查看文件）
  const checked = editPdfCheckedFiles.value
  if (checked.length === 0) {
    showToast('请选择要处理的文件', 'warning')
    return
  }
  const targets = checked

  editPdfProcessSubmitting.value = true
  let states = []
  try {
    states = await Promise.all(targets.map(async (f) => {
      try {
        const res = await api.getEditPdfProcessRecipe(f.task_id, f.file_id)
        return { file: f, recipe: res.data.recipe || null, cleaned: !!res.data.cleaned }
      } catch (err) {
        // 查询失败按未处理对待（宁重复执行不误跳过）
        devLog('error', '[编辑PDF] 状态查询失败，按未处理:', f.name, err)
        return { file: f, recipe: null, cleaned: false }
      }
    }))
  } finally {
    editPdfProcessSubmitting.value = false
  }

  // 回填 cleaned 到文件对象（批量执行循环逐文件跳过已修图成员用）
  states.forEach(s => { s.file.cleaned = s.cleaned })
  editPdfProcessStates.value = states

  // zhaoqiaotong 2026-09-12 五轮整改（FIX-J）勾选回显规则（用户确认）：
  // 仅"全部成员已执行"的项=勾选+置灰锁定；部分已执行/全部未执行=不默认勾选、可选，
  // 部分已执行在描述中标注"（部分已处理）"——用户按需自行勾选，执行层只增不减
  editPdfProcessApplyClean.value = states.every(s => s.cleaned)
  editPdfProcessRemoveBlank.value = states.every(s => s.recipe && !!s.recipe.remove_blank_pages)
  editPdfProcessAddPagenum.value = states.every(s => s.recipe && !!s.recipe.add_page_number)
  editPdfProcessShrink.value = states.every(s => s.recipe && !!s.recipe.shrink)

  showEditPdfProcessModal.value = true
}

// zhaoqiaotong 2026-09-10 研发需求-0167 取消：仅关闭弹窗，不发起任何请求
function editPdfCancelProcess() {
  showEditPdfProcessModal.value = false
}

// zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J）防重复执行·只增不减（方案A）：
// 逐文件判定"是否有新增操作"（勾选修图且该文件未修，或勾选了该文件未生效的配方项），
// 无新增→整文件跳过；执行时每文件最终配方=当前配方∪本次勾选（取消不会回退已生效
// 成员的效果，延续不可回退原则）；全部跳过→提示中止；完成提示汇总跳过数
async function editPdfConfirmProcess() {
  const states = editPdfProcessStates.value
  if (!states.length) return

  const sel = {
    apply_clean: editPdfProcessApplyClean.value,
    remove_blank_pages: editPdfProcessRemoveBlank.value,
    add_page_number: editPdfProcessAddPagenum.value,
    shrink: editPdfProcessShrink.value
  }

  // 新增判定：勾选了该文件尚未执行的操作（修图未修 / 配方项未生效）
  const hasNewFor = (s) =>
    (sel.apply_clean && !s.cleaned) ||
    (sel.remove_blank_pages && !(s.recipe && s.recipe.remove_blank_pages)) ||
    (sel.add_page_number && !(s.recipe && s.recipe.add_page_number)) ||
    (sel.shrink && !(s.recipe && s.recipe.shrink))

  const pending = states.filter(s => hasNewFor(s))
  const skipped = states.length - pending.length

  if (!pending.length) {
    showToast('所选操作均已执行过，无需重复处理；页面编辑可继续，下载时自动包含最新修改', 'warning')
    return
  }

  // 预计算每文件"只增不减"的最终参数（并集配方+按文件跳过修图），挂到文件对象供执行层使用
  pending.forEach(s => {
    s.file._processOpts = {
      apply_clean: sel.apply_clean && !s.cleaned,
      remove_blank_pages: sel.remove_blank_pages || !!(s.recipe && s.recipe.remove_blank_pages),
      add_page_number: sel.add_page_number || !!(s.recipe && s.recipe.add_page_number),
      shrink: sel.shrink || !!(s.recipe && s.recipe.shrink)
    }
  })

  showEditPdfProcessModal.value = false
  if (skipped > 0) {
    showToast(`跳过 ${skipped} 个已执行过所选操作的文件，开始处理其余 ${pending.length} 个`, 'warning')
  }
  // FIX-K2：勾选=处理对象，单文件与批量统一走批量流程（单元素复用已验证的
  // "按文件寻址"逻辑，与当前查看文件彻底解耦）
  await startEditPdfProcess(sel, pending.map(s => s.file), skipped)
}

// zhaoqiaotong 2026-09-12 研发需求-0167 六轮整改（FIX-K2）
// 一键处理效果文案拼装（按后端 effects 摘要如实拼装，未生效项带⚠提示）——
// 自原单文件轮询完成回调抽取，供批量单元素完成的详细效果toast复用
function buildEditPdfProcessEffectText(effects, opts) {
  const parts = []
  if (opts.apply_clean) {
    parts.push(`修图${effects.cleaned_pages || 0}页`)
  }
  if (opts.remove_blank_pages) {
    if (effects.remove_blank_applied) {
      parts.push(`删除空白页${effects.removed_blank_pages > 0 ? effects.removed_blank_pages + '页' : ''}`)
    } else {
      parts.push('未检出空白页')
    }
  }
  if (opts.add_page_number) {
    if (effects.pagenum_applied) {
      parts.push(effects.renumbered ? '已添加页码(旧页码重编)' : '已添加页码')
    } else {
      parts.push('⚠ 页码未添加(详见日志)')
    }
  } else if (effects.pagenum_applied && effects.renumbered) {
    parts.push('旧页码已重编')
  }
  if (opts.shrink) {
    parts.push(effects.shrink_applied ? '已瘦身' : '⚠ 瘦身未生效(详见日志)')
  }
  if (effects.page_count) {
    parts.push(`共${effects.page_count}页`)
  }
  return parts.length ? `：${parts.join('、')}` : ''
}

// zhaoqiaotong 2026-09-12 研发需求-0167 六轮整改（FIX-K2）一键处理执行入口简化：
// 勾选=处理对象——单文件与批量统一走批量流程（editPdfBatchClean 按 task_id+file_id
// 寻址，与当前查看文件彻底解耦；原单文件分支及轮询已随模型调整移除，效果反馈由
// 批量单元素的详细效果toast承接）
async function startEditPdfProcess(opts, pendingFiles = null, skippedCount = 0) {
  const checked = pendingFiles || editPdfCheckedFiles.value
  if (!checked.length) {
    showToast('请选择要处理的文件', 'warning')
    return
  }
  if (editPdfHasChanges.value) {
    showToast('当前页面有未保存的修改，请先保存后再进行一键处理', 'warning')
    return
  }
  for (const file of checked) {
    try {
      const res = await api.checkEditPdfUnsaved(file.task_id, file.file_id)
      if (res.data && res.data.has_unsaved) {
        showToast(`文件「${file.name}」有未保存的修改，请先保存`, 'warning')
        return
      }
    } catch (err) {
      devLog('error', '[编辑PDF] 处理预检失败:', file.name, err)
      showToast(translateError(err, '处理预检失败: '), 'error')
      return
    }
  }
  await editPdfBatchClean(checked, opts, skippedCount)
}


// 停止一键修图
function stopEditPdfCleanAll() {
  if (editPdfCleanTimer) {
    clearInterval(editPdfCleanTimer)
    editPdfCleanTimer = null
  }
  if (editPdfCleanPollTimer) {
    clearInterval(editPdfCleanPollTimer)
    editPdfCleanPollTimer = null
  }
}

// 关闭编辑PDF一键修图进度条
function closeEditPdfCleanProgress() {
  stopEditPdfCleanAll()
  hideGlobalLoading()
  showEditPdfCleanProgress.value = false
  editPdfCleanProgress.value = {
    currentPage: 0,
    totalPages: 0,
    phase: '',
    message: '',
    status: '',
    isDualLayer: false
  }
}

// zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
// 静默清除一键处理完成横幅（新上传/导入文件时调用：提示针对旧任务已过期）。
// 与 closeEditPdfCleanProgress 的差别：不动全局遮罩——上传/导入流程有自己的遮罩时序
function dismissEditPdfCleanProgressBanner() {
  if (!showEditPdfCleanProgress.value) return
  stopEditPdfCleanAll()
  showEditPdfCleanProgress.value = false
  editPdfCleanProgress.value = {
    currentPage: 0,
    totalPages: 0,
    phase: '',
    message: '',
    status: '',
    isDualLayer: false
  }
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 从批量修图的单文件失败中提取后端原因：FastAPI HTTPException 返回 {detail:"..."}
// （如"PDF文件不存在"），无 detail 时回退通用错误翻译——失败汇总不再只报文件名
function extractEditPdfBatchFailReason(err) {
  const detail = err && err.response && err.response.data && err.response.data.detail
  if (detail) return String(detail)
  return translateError(err, '请求失败')
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 批量修图失败明细格式化：逐个"文件名：原因"，超过3个仅展示前3个防止toast过长
function formatEditPdfBatchFailures(failedFiles) {
  const parts = failedFiles.map(f => `${f.name}：${f.reason}`)
  if (parts.length > 3) {
    return parts.slice(0, 3).join('；') + `；等${parts.length}个`
  }
  return parts.join('；')
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 一键处理执行（单文件与批量统一走本函数，FIX-K2 勾选=处理对象）：对目标集合逐个
// 文件顺序调用 clean-all-pages 接口并轮询进度（接口按 task_id+file_id 独立寻址，
// 与当前查看文件解耦；后端对未查看过的文件会先补渲染页面再修图）；GPU 重操作串行
// 执行不并发；单个文件失败记入失败清单（含失败原因）继续下一个，结束汇总提示
// zhaoqiaotong 2026-09-12 六轮整改（FIX-K）：单元素时进度/提示不带批量序号，完成
// 显示详细效果toast（与原单文件体验一致）；文件列表"已修改"徽标无条件置位
// （仅勾配方项处理也算已处理过，FIX-K1）
async function editPdfBatchClean(checkedFiles, opts = {}, skippedCount = 0) {
  const total = checkedFiles.length
  const failedFiles = []
  const isSingle = total === 1

  editPdfBatchCleaning.value = true
  editPdfBusy.value = true
  showEditPdfCleanProgress.value = true
  showGlobalLoading(isSingle ? `正在一键处理「${checkedFiles[0].name}」...` : `正在批量一键处理（共 ${total} 个文件）...`)
  editPdfCleanProgress.value = {
    currentPage: 0,
    totalPages: checkedFiles[0].total_pages,
    phase: 'cleaning',
    message: '正在初始化...',
    status: 'processing',
    isDualLayer: false
  }
  editPdfCleanElapsed.value = 0
  editPdfCleanTimer = setInterval(() => {
    editPdfCleanElapsed.value++
  }, 1000)

  try {
    let singleEffectText = ''
    // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    // 页码效果引导标记：任一成功处理的文件勾选了添加页码则完成提示追加"到操作记录
    // 预览/下载"引导（页码只落在成品PDF，工作区页面图不含页码，刷新修图区看不到）
    let anyPagenumApplied = false
    for (let i = 0; i < total; i++) {
      const file = checkedFiles[i]
      editPdfCleanProgress.value = {
        currentPage: 0,
        totalPages: file.total_pages,
        phase: 'cleaning',
        message: isSingle ? `「${file.name}」正在初始化...` : `第 ${i + 1}/${total} 个文件「${file.name}」正在初始化...`,
        status: 'processing',
        isDualLayer: false
      }
      showGlobalLoading(isSingle ? `正在一键处理「${file.name}」: 正在初始化...` : `批量一键处理（${i + 1}/${total}）「${file.name}」: 正在初始化...`)

      try {
        // zhaoqiaotong 2026-09-10 研发需求-0167 携带一键处理参数（apply_clean+三项配方）
        // zhaoqiaotong 2026-09-12 五轮整改（FIX-J）逐文件使用"只增不减"合并参数：
        // 该文件最终配方=用户勾选∪其当前配方（取消不回退已生效项）；已修图不重跑AI清洁
        const fopts = file._processOpts || opts
        const response = await api.cleanAllEditPdfPages({
          task_id: file.task_id,
          file_id: file.file_id,
          ocr_lang: editPdfOcrLang.value,
          apply_clean: fopts.apply_clean,
          remove_blank_pages: fopts.remove_blank_pages,
          add_page_number: fopts.add_page_number,
          shrink: fopts.shrink
        })
        if (!response.data.success) {
          failedFiles.push({ name: file.name, reason: response.data.message || '启动失败' })
          continue
        }

        // 顺序等待该文件处理完成（只更新进度UI，不切换查看视图）
        const result = await waitForEditPdfFileCleanDone(file, i, total)
        if (result.ok) {
          if (fopts.add_page_number) {
            anyPagenumApplied = true
          }
          const idx = editPdfFileList.value.findIndex(f => f.file_id === file.file_id)
          if (idx >= 0) {
            // FIX-K1 "已修改"=该文件已被处理过（修图或仅配方项），无条件置位
            editPdfFileList.value[idx].modified = true
            if (fopts.apply_clean) {
              editPdfFileList.value[idx].cleaned = true
            }
          }
          // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
          // 仅勾修图（apply_clean）时刷新当前查看文件（页面像素已变，重新拉列表拿新version
          // 重建URL）；仅配方路径页面产物零改动不刷新（页码/瘦身效果在成品，走操作记录预览，
          // 原"无条件全量重下约200MB"是纯浪费）。await 与批量完成后的空白页重查串行化，
          // 防止写缓存与重查交错覆盖
          if (fopts.apply_clean) {
            if (editPdfCurrentFileInfo.value && editPdfCurrentFileInfo.value.file_id === file.file_id) {
              await refreshEditPdfCurrentFilePages(file)
            }
          }
          // FIX-K2 单元素完成记录详细效果文案（完成后展示，与原单文件体验一致）
          if (isSingle && result.effects) {
            singleEffectText = buildEditPdfProcessEffectText(result.effects, fopts)
          }
        } else {
          failedFiles.push({ name: file.name, reason: result.reason || '处理失败' })
        }
      } catch (err) {
        devLog('error', '[编辑PDF] 批量处理单文件失败:', file.name, err)
        failedFiles.push({ name: file.name, reason: extractEditPdfBatchFailReason(err) })
      }
    }

    // FIX-I 完成提示汇总跳过数（方案B用户确认）：成功/失败分支均体现
    // FIX-K2 单元素成功时显示详细效果（与原单文件体验一致），多元素保持汇总
    const skipNote = skippedCount > 0 ? `，跳过 ${skippedCount} 个已执行过` : ''
    // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    // 涉及添加页码时追加简洁引导：成品页码效果到操作记录预览/下载查看（toast与横幅同文案）
    const pagenumHint = anyPagenumApplied ? '；页码效果可在操作记录预览/下载' : ''
    let summaryText
    if (failedFiles.length === 0) {
      summaryText = isSingle
        ? `一键处理完成${singleEffectText}，成品已生成，点击「下载PDF」即可获取${pagenumHint}`
        : `批量一键处理完成！共处理 ${total} 个文件${skipNote}，成品已生成，处理明细见操作记录${pagenumHint}`
    } else {
      summaryText = isSingle
        ? `一键处理失败：${failedFiles[0].name}：${failedFiles[0].reason}`
        : `批量一键处理结束：成功 ${total - failedFiles.length} 个，失败 ${failedFiles.length} 个${skipNote}（${formatEditPdfBatchFailures(failedFiles)}）`
    }
    editPdfCleanProgress.value.status = 'completed'
    editPdfCleanProgress.value.phase = 'done'
    editPdfCleanProgress.value.message = isSingle && failedFiles.length === 0
      ? `一键处理完成${singleEffectText}${pagenumHint}`
      : summaryText
    showToast(summaryText, failedFiles.length === 0 ? 'success' : 'warning')

    // FIX-J3 批量完成后对当前查看文件重查空白页判定（批量构建不经过单文件完成回调）
    const curFile = editPdfCurrentFileInfo.value
    if (curFile) {
      try {
        const recipeRes = await api.getEditPdfProcessRecipe(curFile.task_id, curFile.file_id)
        editPdfBlankPages.value = recipeRes.data.blank_pages || []
      } catch (err) {
        devLog('error', '[编辑PDF] 批量完成后空白页判定查询失败:', err)
      }
    }
  } finally {
    stopEditPdfCleanAll()
    editPdfBatchCleaning.value = false
    editPdfBusy.value = false
    hideGlobalLoading()
  }
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 轮询指定文件的一键修图进度直至完成/失败，resolve {ok, reason, effects}：
// 后端 failed 时携带进度消息作为失败原因（如"页面提取失败..."）；completed 时携带
// effects 效果摘要（FIX-K2：供批量单元素的详细效果toast复用）；
// 网络抖动容忍：连续失败10次（约5秒）判定该文件失败（reason="进度查询连续失败"）
function waitForEditPdfFileCleanDone(file, fileIndex, fileTotal) {
  return new Promise((resolve) => {
    let finished = false
    let pollFailCount = 0
    const finish = (ok, reason, effects) => {
      if (finished) return
      finished = true
      clearInterval(pollTimer)
      resolve({ ok, reason: reason || '', effects: effects || null })
    }
    const pollTimer = setInterval(async () => {
      try {
        const response = await api.getCleanAllProgress(file.task_id, file.file_id)
        pollFailCount = 0
        const progress = response.data
        if (!progress || progress.status === 'idle') return

        // FIX-K2 单元素时不带"第x/N个"序号前缀（与原单文件体验一致）
        const prefix = fileTotal > 1 ? `第 ${fileIndex + 1}/${fileTotal} 个「${file.name}」: ` : `「${file.name}」: `
        editPdfCleanProgress.value = {
          currentPage: progress.current_page || 0,
          totalPages: progress.total_pages || file.total_pages,
          phase: progress.phase || 'cleaning',
          message: `${prefix}${progress.message || '处理中...'}`
        }
        if (progress.message) {
          const loadPrefix = fileTotal > 1 ? `批量一键处理（${fileIndex + 1}/${fileTotal}）` : '正在一键处理'
          showGlobalLoading(`${loadPrefix}「${file.name}」: ${progress.message}`)
        }

        if (progress.status === 'completed') {
          finish(true, '', progress.effects)
        } else if (progress.status === 'failed') {
          finish(false, progress.message || '处理失败')
        }
      } catch (err) {
        devLog('error', '[编辑PDF] 批量修图轮询进度失败:', file.name, err)
        pollFailCount++
        if (pollFailCount >= 10) {
          finish(false, '进度查询连续失败')
        }
      }
    }, 500)
  })
}

// zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
// 一键处理完成后刷新当前查看文件的页面图：zhaoqiaotong 2026-09-17 研发BUG-0057 改为
// 重新拉取页面列表（拿权威内容版本号重建全部URL——修图bump后version必+1，URL全换新
// 强制重新下载修图后新图；未变化的页内容也变URL会重下，属修图场景的必要代价），
// 静默刷新无遮罩并重初始化画布。仅勾修图（apply_clean）时调用——仅配方路径页面产物
// 零改动（页码/瘦身只落在成品PDF，效果查看走操作记录预览），不刷新不重下
async function refreshEditPdfCurrentFilePages(file) {
  try {
    const response = await api.getEditPdfFilePages(file.task_id, file.file_id)
    const data = response.data
    if (!data.success) {
      devLog('error', '[编辑PDF] 修图后刷新页面列表失败:', data.message)
      return
    }
    const version = (data.version !== undefined && data.version !== null) ? data.version : editPdfCurrentVersion.value
    editPdfCurrentVersion.value = version
    // 修图后每页都可"一键还原"（回到修图前backup），保留原刷新逻辑的 modified=true/edited=null 语义
    editPdfPages.value = data.pages.map((page, i) => ({
      thumbnail: `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${i}/thumbnail?v=${version}`,
      original: `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${i}/original?v=${version}`,
      edited: null,
      modified: true
    }))

    const pageNum = editPdfCurrentPage.value
    editPdfOriginalPageUrl.value = `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${pageNum}/backup?v=${version}`
    editPdfCurrentPageUrl.value = `/api/edit-pdf/page/${file.task_id}/${file.file_id}/${pageNum}/original?v=${version}`
    editPdfEditedPageUrl.value = editPdfCurrentPageUrl.value

    setTimeout(() => {
      initEditPdfCanvas()
    }, 100)
  } catch (err) {
    devLog('error', '[编辑PDF] 修图后刷新页面列表失败:', err)
  }
}



// 下载PDF
// zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 下载简化为"取构建结果"：不携带任何处理参数（配方由一键处理设置并长期生效），
// 下载零处理决策、零记录写入；未编辑过的文件后端直接复用成品（秒级）
async function editPdfDownload() {
  if (!editPdfCurrentFileInfo.value) return

  // zhaoqiaotong 2026-09-12 六轮整改（FIX-K2）勾选=下载对象（与一键处理同模型）：
  // 勾选≥2批量ZIP；勾选1个下载勾选的那个文件（不再回退当前查看文件）；0勾选按钮已禁用
  const checked = editPdfCheckedFiles.value
  const file = checked.length === 1 ? checked[0] : editPdfCurrentFileInfo.value

  // zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
  // 勾选≥2个时走批量下载分支：逐文件预检未保存修改后，一次下载ZIP；
  // 勾选1个走下方单文件下载逻辑（下载勾选的文件）
  if (checked.length >= 2) {
    if (editPdfHasChanges.value) {
      showToast('当前页面有未保存的修改，请先保存后再下载', 'warning')
      return
    }
    for (const item of checked) {
      try {
        const res = await api.checkEditPdfUnsaved(item.task_id, item.file_id)
        if (res.data && res.data.has_unsaved) {
          showToast(`文件「${item.name}」有未保存的修改，请先保存`, 'warning')
          return
        }
      } catch (err) {
        devLog('error', '[编辑PDF] 批量下载预检失败:', item.name, err)
        showToast(translateError(err, '批量下载预检失败: '), 'error')
        return
      }
    }

    const url = api.getEditPdfBatchDownloadUrl(
      checked[0].task_id,
      checked.map(f => f.file_id)
    )
    window.open(url, '_blank')
    showToast(`正在批量下载 ${checked.length} 个PDF（ZIP打包）...`, 'success')

    // 如果是从转换记录进入编辑的，标记为编辑后下载
    const pending = pdfStore.pendingEdit
    if (pending && pending.history_index !== undefined) {
      try {
        await api.markHistoryEditDownloaded(pending.history_index)
      } catch (err) {
        devLog('error', '[编辑PDF] 标记编辑后下载失败:', err)
      }
    }
    return
  }

  if (editPdfHasChanges.value) {
    showToast('当前页面有未保存的修改，请先保存后再下载', 'warning')
    return
  }

  try {
    const checkResponse = await api.checkEditPdfUnsaved(file.task_id, file.file_id)
    const checkData = checkResponse.data

    if (checkData.has_unsaved) {
      showToast(`页面 ${checkData.unsaved_pages.map(p => p + 1).join(', ')} 有未保存的修改，请先保存`, 'warning')
      return
    }

    const url = `/api/edit-pdf/download/${file.task_id}/${file.file_id}`
    window.open(url, '_blank')
    showToast('正在下载处理完成后的PDF...', 'success')

    // 如果是从转换记录进入编辑的，标记为编辑后下载
    const pending = pdfStore.pendingEdit
    if (pending && pending.history_index !== undefined) {
      try {
        await api.markHistoryEditDownloaded(pending.history_index)
      } catch (err) {
        devLog('error', '[编辑PDF] 标记编辑后下载失败:', err)
      }
    }
  } catch (error) {
    devLog('error', '[编辑PDF] 下载检查失败:', error)
    showToast(translateError(error, '下载失败: '), 'error')
  }
}

// 显示操作记录
async function editPdfShowHistory() {
  try {
    const res = await api.getEditPdfHistory()
    editPdfHistoryList.value = res.data.history || []
  } catch (err) {
    devLog('error', '[编辑PDF] 加载操作记录失败:', err)
    showToast('操作记录加载失败', 'error')
  }
  showEditPdfHistoryModal.value = true
}

// zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
// 以下三操作改为按记录键 task_id+file_id 寻址：原 realIndex 下标在"取列表后、点击前"
// 发生记录插入（一键处理 insert(0)）时全体错位，会预览/下载/删除到别的文件（GUI复测实测）
// 下载操作记录中的PDF
async function downloadEditPdfHistoryItem(index, item) {
  try {
    const response = await api.downloadEditPdfHistoryBlob(item.task_id, item.file_id)
    let filename = item.filename || 'output.pdf'
    const contentDisposition = response.headers['content-disposition']
    if (contentDisposition) {
      const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/i)
      if (utf8Match) filename = decodeURIComponent(utf8Match[1])
    }
    const blob = response.data
    const blobUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(blobUrl)
    const rec = editPdfHistoryList.value.find(r => r.task_id === item.task_id && r.file_id === item.file_id)
    if (rec) {
      rec.download_count = (rec.download_count || 0) + 1
    }
    showToast('下载完成', 'success')
  } catch (err) {
    showToast(translateError(err, '下载失败: '), 'error')
  }
}

// 预览操作记录中的PDF（按键寻址+URL缓存戳）
function previewEditPdfHistoryItem(index, item) {
  const url = api.getEditPdfHistoryPreviewUrl(item.task_id, item.file_id)
  window.open(url, '_blank')
}

// 删除操作记录（按键寻址，本地列表按键定位后删除）
// xuechong 2026-10-10 研发BUG-0071 用户复验：删除改弹统一站内确认框（原浏览器原生confirm），
// ask 打开确认框、confirm 执行原删除逻辑
const editPdfDeleteConfirm = ref(null)

function askDeleteEditPdfHistoryItem(index, item) {
  editPdfDeleteConfirm.value = { index, item }
}

async function confirmEditPdfHistoryDelete() {
  const target = editPdfDeleteConfirm.value
  if (!target) return
  editPdfDeleteConfirm.value = null
  const item = target.item
  try {
    await api.deleteEditPdfHistory(item.task_id, item.file_id)
    const idx = editPdfHistoryList.value.findIndex(r => r.task_id === item.task_id && r.file_id === item.file_id)
    if (idx >= 0) {
      editPdfHistoryList.value.splice(idx, 1)
    }
    showToast('记录已删除', 'success')
    if (editPdfPaginatedHistory.value.length === 0 && editPdfHistoryPage.value > 1) {
      editPdfHistoryPage.value--
    }
  } catch (err) {
    // xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改 错误翻译（detail优先已在translateError内）
    showToast(translateError(err, '删除失败: '), 'error')
  }
}

// 处理编辑PDF原图加载失败
function handleEditPdfOriginalError() {
  if (editPdfOriginalPageUrl.value && editPdfCurrentPageUrl.value) {
    devLog('[编辑PDF] 备份原图加载失败，使用当前工作图')
    editPdfOriginalPageUrl.value = editPdfCurrentPageUrl.value
  }
}

// 编辑PDF滚轮缩放
function handleEditPdfWheel(event) {
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.max(0.1, Math.min(5, editPdfScale.value + delta))
  editPdfScale.value = newScale
}

// 编辑PDF拖拽开始
function startEditPdfDrag(event) {
  if (event.button !== 0) return
  editPdfIsDragging.value = true
}

// 编辑PDF拖拽中
function onEditPdfDrag(event) {
  if (!editPdfIsDragging.value) return
  editPdfPosition.value.x += event.movementX / editPdfScale.value
  editPdfPosition.value.y += event.movementY / editPdfScale.value
}

// 编辑PDF拖拽结束
function stopEditPdfDrag() {
  editPdfIsDragging.value = false
}

// 初始化编辑PDF画布
function initEditPdfCanvas() {
  const canvas = editPdfCanvas.value
  const img = editPdfEditedImage.value

  if (!canvas || !img) {
    devLog('[编辑PDF] 画布或图片元素不存在')
    return
  }

  if (!img.complete || !img.naturalWidth) {
    devLog('[编辑PDF] 图片尚未加载完成')
    img.addEventListener('load', () => initEditPdfCanvas(), { once: true })
    return
  }

  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight

  canvas.style.width = img.offsetWidth + 'px'
  canvas.style.height = img.offsetHeight + 'px'

  editPdfCanvasCtx = canvas.getContext('2d')

  editPdfCanvasCtx.imageSmoothingEnabled = false
  editPdfCanvasCtx.drawImage(img, 0, 0)

  editPdfSaveToHistory()

  devLog('[编辑PDF] 画布初始化完成:', canvas.width, 'x', canvas.height)
}

// 保存画布状态到历史记录
function editPdfSaveToHistory() {
  if (!editPdfCanvasCtx || !editPdfCanvas.value) return

  const canvas = editPdfCanvas.value
  const imageData = editPdfCanvasCtx.getImageData(0, 0, canvas.width, canvas.height)

  if (editPdfHistoryIndex.value < editPdfHistory.value.length - 1) {
    editPdfHistory.value = editPdfHistory.value.slice(0, editPdfHistoryIndex.value + 1)
  }

  editPdfHistory.value.push(imageData)
  editPdfHistoryIndex.value = editPdfHistory.value.length - 1

  if (editPdfHistory.value.length > 50) {
    editPdfHistory.value.shift()
    editPdfHistoryIndex.value--
  }

  editPdfCanUndo.value = editPdfHistoryIndex.value > 0
  editPdfCanRedo.value = editPdfHistoryIndex.value < editPdfHistory.value.length - 1
}

// 编辑PDF绘制开始
function startEditPdfDraw(event) {
  devLog('[编辑PDF] 开始绘制')

  if (!editPdfCanvasCtx) {
    initEditPdfCanvas()
  }
  if (!editPdfCanvasCtx) {
    devLog('[编辑PDF] 画布上下文不存在')
    return
  }

  editPdfIsDrawing.value = true
  editPdfHasDrawn.value = false
  editPdfLastDrawPos.value = null
  editPdfDraw(event)
}

// 编辑PDF绘制中
function editPdfDraw(event) {
  if (!editPdfIsDrawing.value || !editPdfCanvasCtx || !editPdfCanvas.value || !editPdfEditedImage.value) return

  const canvas = editPdfCanvas.value
  const img = editPdfEditedImage.value
  const imgRect = img.getBoundingClientRect()

  const mouseX = event.clientX - imgRect.left
  const mouseY = event.clientY - imgRect.top

  const canvasX = (mouseX / imgRect.width) * canvas.width
  const canvasY = (mouseY / imgRect.height) * canvas.height

  if (canvasX < 0 || canvasX > canvas.width || canvasY < 0 || canvasY > canvas.height) {
    editPdfLastDrawPos.value = null
    return
  }

  const displayToCanvasRatio = canvas.width / imgRect.width
  const brushRadius = 10 * displayToCanvasRatio

  editPdfCanvasCtx.fillStyle = '#FFFFFF'
  editPdfCanvasCtx.strokeStyle = '#FFFFFF'
  editPdfCanvasCtx.lineCap = 'round'
  editPdfCanvasCtx.lineJoin = 'round'
  editPdfCanvasCtx.lineWidth = brushRadius * 2

  if (editPdfLastDrawPos.value) {
    editPdfCanvasCtx.beginPath()
    editPdfCanvasCtx.moveTo(editPdfLastDrawPos.value.x, editPdfLastDrawPos.value.y)
    editPdfCanvasCtx.lineTo(canvasX, canvasY)
    editPdfCanvasCtx.stroke()
  }

  editPdfCanvasCtx.beginPath()
  editPdfCanvasCtx.arc(canvasX, canvasY, brushRadius, 0, Math.PI * 2)
  editPdfCanvasCtx.fill()

  editPdfLastDrawPos.value = { x: canvasX, y: canvasY }

  editPdfHasDrawn.value = true

  if (!editPdfHasChanges.value) {
    editPdfHasChanges.value = true
    editPdfCanRestore.value = true
  }
}

// 编辑PDF绘制结束
function stopEditPdfDraw() {
  if (editPdfIsDrawing.value) {
    devLog('[编辑PDF] 停止绘制')
    editPdfIsDrawing.value = false
    editPdfLastDrawPos.value = null

    if (editPdfHasDrawn.value) {
      editPdfSaveToHistory()
      editPdfHasDrawn.value = false
    }
  }
}

// ============================================================
// 从 pdfStore.pendingEdit 初始化编辑内容
// 首次挂载和从 keep-alive 缓存恢复时均会调用
// ============================================================
function resetEditPdfState() {
  editPdfTaskInfo.value = null
  editPdfFileList.value = []
  editPdfSelectedFile.value = -1
  editPdfPages.value = []
  // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
  // 内容版本号随状态整体重置一并归零（keep-alive 恢复/导入新PDF场景）
  editPdfCurrentVersion.value = 0
  editPdfCurrentPage.value = 0
  editPdfOriginalPageUrl.value = ''
  editPdfCurrentPageUrl.value = ''
  editPdfEditedPageUrl.value = ''
  editPdfHasChanges.value = false
  editPdfCanUndo.value = false
  editPdfCanRedo.value = false
  editPdfCanRestore.value = false
  editPdfScale.value = 1
  editPdfPosition.value = { x: 0, y: 0 }
  editPdfHistory.value = []
  editPdfHistoryIndex.value = -1
  editPdfCanvasCtx = null
  editPdfSource.value = null
  showEditPdfCleanProgress.value = false
  editPdfCleanProgress.value = { currentPage: 0, totalPages: 0, phase: '', message: '', status: '', isDualLayer: false }
  editPdfCleanElapsed.value = 0
  editPdfOcrAllRunning.value = false
  editPdfUploadProgress.value = { visible: false, current: 0, total: 0, percent: 0, message: '' }
  // FIX-J3 状态整体重置时空白页角标一并复位
  editPdfBlankPages.value = []
  // zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
  // 状态整体重置时一键处理弹窗一并复位（原三个下载开关复位逻辑随开关移除；配方为
  // 文件级设置存于后端，随任务目录生命周期自然清理）
  showEditPdfProcessModal.value = false
  editPdfProcessSubmitting.value = false
  // zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
  // 状态整体重置时批量修图标志一并复位（文件列表已清空，勾选状态随之消失）
  editPdfBatchCleaning.value = false
}

async function initFromPendingEdit() {
  const pending = pdfStore.pendingEdit
  if (!pending) {
    hideGlobalLoading()
    pageReady.value = true
    return
  }

  // 立即清空旧状态并显示loading，避免 keep-alive 缓存闪现旧内容
  resetEditPdfState()
  editPdfSource.value = pending.source || null
  pdfStore.clearPendingEdit()
  editPdfBusy.value = true
  showGlobalLoading('正在导入PDF...')

  try {
    const body = {}
    if (pending.pdfPath) {
      body.pdf_path = pending.pdfPath
    } else if (pending.task_id) {
      body.task_id = pending.task_id
    }
    body.source = pending.source || 'manual'

    const response = await api.importEditPdf(body)

    const data = response.data

    if (data.success) {
      editPdfTaskInfo.value = {
        task_id: data.task_id,
        folder_name: data.folder_name || pending.fileName || '导入的PDF',
        total_files: data.files.length
      }

      // zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 导入新文件：静默清除上一轮一键处理完成横幅（与上传入口同语义）
      dismissEditPdfCleanProgressBanner()
      editPdfFileList.value = data.files.map((file, idx) => ({
        name: file.filename,
        path: file.path,
        total_pages: file.total_pages,
        task_id: data.task_id,
        file_id: file.file_id,
        modified: false,
        // zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
        // 导入PDF同样默认仅勾选第一个文件（与上传入口一致，默认不执行批量操作）
        checked: idx === 0
      }))

      // zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
      // 加 await（与上传入口同修）：防 finally 的 hideGlobalLoading 提前关掉首文件加载遮罩
      if (editPdfFileList.value.length > 0) {
        await selectEditPdfFile(0)
      }

      showToast(`已导入 ${data.files.length} 个PDF文件`, 'success')
    } else {
      showToast(data.message || data.detail || '导入失败', 'error')
    }
  } catch (err) {
    devLog('error', '[编辑PDF] 导入失败:', err)
    showToast(translateError(err, '导入失败: '), 'error')
  } finally {
    editPdfBusy.value = false
    hideGlobalLoading()
    pageReady.value = true
  }
}

// 注意：EditPdfPage 在 keep-alive 中，onMounted 和 onActivated 在首次挂载时都会触发。
// 若 onMounted 中也调用 initFromPendingEdit，会与 onActivated 竞争导致 pendingEdit
// 被提前清除，进而丢失 editPdfSource（返回按钮文案错误）。因此仅由 onActivated 负责初始化。
onActivated(async () => {
  // keep-alive 缓存恢复时 pageReady=false → 显示loading → 加载数据 → pageReady=true
  pageReady.value = false
  stopEditPdfCleanAll()
  editPdfOcrAllRunning.value = false
  hideGlobalLoading()
  // resetEditPdfState 由 initFromPendingEdit 内部调用，此处不重复调用
  await nextTick()
  initFromPendingEdit()
})

// 离开前设 pageReady=false 并等 DOM 刷新，确保 keep-alive 缓存的是 loading 画面
onBeforeRouteLeave(async () => {
  stopEditPdfCleanAll()
  editPdfOcrAllRunning.value = false
  hideGlobalLoading()
  resetEditPdfState()
  pageReady.value = false
  await nextTick()
})

// 组件销毁时清理定时器（防止直接销毁而非路由跳转时的泄漏）
onUnmounted(() => {
  stopEditPdfCleanAll()
  editPdfOcrAllRunning.value = false
})
</script>

<style scoped>
/* zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 */
/* 批量勾选交互样式：列表项勾选框/列表头全选控件（批量一键修图/批量下载的作用范围） */
.edit-pdf-page .pdf-file-checkbox {
  width: 15px;
  height: 15px;
  margin: 0;
  flex-shrink: 0;
  cursor: pointer;
  accent-color: var(--primary-color);
}
.edit-pdf-page .batch-select-all {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  cursor: pointer;
  color: var(--text-secondary);
  white-space: nowrap;
}
.edit-pdf-page .batch-select-all input[type="checkbox"] {
  width: 15px;
  height: 15px;
  margin: 0;
  flex-shrink: 0;
  cursor: pointer;
  accent-color: var(--primary-color);
}

/* zhaoqiaotong 2026-09-11 GUI复测二轮整改 样式收紧：选项行紧凑化、禁用态 */
/* zhaoqiaotong 2026-09-11 二轮二批整改 提示条删除、弹窗收窄、锁定项文字弱化 */
/* zhaoqiaotong 2026-09-12 五轮整改 加宽回560：描述追加"（部分已处理）"后避免换行 */
.edit-pdf-process-dialog {
  width: 560px;
  max-width: calc(100vw - 40px);
}
.edit-pdf-process-dialog .process-scope {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 14px;
}
.edit-pdf-process-dialog .scope-label {
  color: #999;
  flex-shrink: 0;
}
.edit-pdf-process-dialog .scope-value {
  color: #333;
  font-weight: 500;
  word-break: break-all;
}
.edit-pdf-process-dialog .process-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  border: 1px solid #e4e4e4;
  border-radius: 6px;
  cursor: pointer;
  background: #fff;
  transition: border-color 0.15s, background 0.15s;
}
.edit-pdf-process-dialog .process-option:hover {
  border-color: var(--primary-color, #EA580C);
}
.edit-pdf-process-dialog .process-option.checked {
  border-color: var(--primary-color, #EA580C);
  background: var(--primary-light-bg, #FFF7ED);
}
.edit-pdf-process-dialog .process-option.disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: #fafafa;
}
.edit-pdf-process-dialog .process-option.disabled:hover {
  border-color: #e4e4e4;
}
.edit-pdf-process-dialog .process-option input[type="checkbox"] {
  width: 15px;
  height: 15px;
  margin: 0;
  flex-shrink: 0;
  accent-color: var(--primary-color, #EA580C);
  cursor: pointer;
}
.edit-pdf-process-dialog .process-option.disabled input[type="checkbox"] {
  cursor: not-allowed;
}
.edit-pdf-process-dialog .option-name {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  flex-shrink: 0;
}
.edit-pdf-process-dialog .option-desc {
  font-size: 14px;
  color: #999;
  line-height: 1.4;
}
.edit-pdf-process-dialog .itp-history-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 10px 14px;
  border-top: 1px solid #eee;
}

/* keep-alive 缓存恢复时的初始化loading（完全不透明，彻底遮挡旧内容） */
.edit-pdf-init-loading {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: #f5f5f5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  z-index: 100000;
}
.edit-pdf-init-loading .global-loading-text {
  font-size: 16px;
  color: #333;
  font-weight: 500;
}

/* 编辑PDF独立页面布局 */
.edit-pdf-page {
  width: 100vw;
  max-width: 100vw;
  height: 100vh;
  max-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.edit-pdf-page .sidebar {
  height: 100%;
}

.edit-pdf-page .main-content {
  height: 100%;
}

/* PDF文件列表 */
.edit-pdf-page .pdf-file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  max-height: 200px;
  overflow-y: auto;
}

.edit-pdf-page .pdf-file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f8f9fa;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.edit-pdf-page .pdf-file-item:hover {
  background: #f0f0f0;
}

.edit-pdf-page .pdf-file-item.selected {
  /* xuechong 2026-10-09 研发BUG-0071 选中色并入主色（原旧橙 rgba(232,97,0)），与文件树选中一致 */
  background: rgba(234, 88, 12, 0.08);
  border-color: var(--primary-color);
}

.edit-pdf-page .pdf-file-item .file-icon {
  font-size: 16px;
}

.edit-pdf-page .pdf-file-item .file-name {
  flex: 1;
  font-size: 14px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.edit-pdf-page .pdf-file-item .file-pages {
  font-size: 14px;
  color: var(--text-secondary);
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
}

/* 页面缩略图列表 */
.edit-pdf-page .pdf-page-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  max-height: calc(100vh - 500px);
  overflow-y: auto;
}

.edit-pdf-page .pdf-page-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: #f8f9fa;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.edit-pdf-page .pdf-page-item:hover {
  background: #f0f0f0;
}

.edit-pdf-page .pdf-page-item.selected {
  background: rgba(232, 97, 0, 0.08);
  border-color: var(--primary-color);
}

.edit-pdf-page .page-thumbnail {
  width: 40px;
  height: 56px;
  object-fit: cover;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.edit-pdf-page .page-number {
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
}

.edit-pdf-page .modified-badge {
  font-size: 14px;
  padding: 2px 8px;
  background: var(--warning-color);
  color: white;
  border-radius: 4px;
  font-weight: 500;
}

/* zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）空白页角标样式：
   被判为空白页（去空白配方生效）的缩略图半透明置灰+覆盖角标文字，页号仍显示（不删列表项） */
.edit-pdf-page .blank-page-item {
  opacity: 0.75;
}
.edit-pdf-page .blank-page-item .page-thumbnail {
  opacity: 0.4;
}
.edit-pdf-page .blank-page-badge {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 14px;
  line-height: 1.3;
  padding: 2px 4px;
  color: #999;
  white-space: nowrap;
}

/* zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）修图区空白页水印：
   预览面板内容区居中大字斜排水印，与左侧列表角标同源（editPdfBlankPages）同消；
   pointer-events:none 保证不拦截画笔/拖拽/缩放操作 */
.edit-pdf-page .blank-page-watermark {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) rotate(-18deg);
  font-size: 18px;
  font-weight: 600;
  color: #aaa;
  letter-spacing: 2px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 6px 14px;
  pointer-events: none;
  z-index: 5;
  white-space: nowrap;
}

/* 预览区域使用 itp-preview-* 全局样式（来自 main.css） */

.ocr-btn {
  background: var(--primary-color);
  color: #fff;
}
.ocr-btn:hover:not(:disabled) {
  background: var(--primary-dark);
}
.ocr-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ocr-lang-select {
  padding: 0 8px;
  height: 36px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 14px;
  background: #fff;
  cursor: pointer;
}
</style>
