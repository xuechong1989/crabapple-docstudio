<template>
  <!-- 一键修图转圈动画 -->
  <div v-if="batchCleaning" class="itp-batch-spinner-wrap">
    <div class="itp-batch-spinner">
      <div class="itp-batch-spinner-ring"></div>
      <div class="itp-batch-spinner-ring"></div>
      <div class="itp-batch-spinner-ring"></div>
    </div>
    <div class="itp-batch-hint">正在一键修图中，请稍候...</div>
  </div>

  <div class="itp-page" :class="{ 'auto-mode': operationMode === 'auto' }">
    <!-- 顶部导航 -->
    <div class="itp-header">
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：左上角补系统logo图标+版本号（复用首页顶栏同款结构样式） -->
      <div class="logo-container">
        <img class="logo-icon" src="../assets/logo-white.png" alt="Logo" />
        <div class="title-text">
          <h1>图转PDF</h1>
          <span class="version">V3.4.00</span>
        </div>
      </div>
      <div class="header-actions">
        <button class="itp-back-btn" @click="showHistoryModal = true"><AppIcon name="clipboard" :size="13" /> 转换记录</button>
        <button class="itp-back-btn" @click="showUploadHistoryModal = true"><AppIcon name="inbox" :size="13" /> 上传记录</button>
        <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
             未完成任务入口：进入页面不再自动恢复，从此处主动恢复 -->
        <button class="itp-back-btn itp-unfinished-btn" @click="openUnfinishedModal" title="查看未转换完成的任务">
          <!-- xuechong 2026-10-09 研发BUG-0071 未完成任务图标：emoji 换单色线性 SVG -->
          <AppIcon name="hourglass" /> 未完成任务<span v-if="unfinishedCount > 0" class="itp-unfinished-badge">{{ unfinishedCount }}</span>
        </button>
        <HeaderActions />
        <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：用户徽章与返回按钮互换（返回收尾最右） -->
        <UserBadge :show-logout="false" />
        <button class="itp-back-btn" @click="handleBack"><AppIcon name="arrow-left" :size="13" /> 返回首页</button>
      </div>
    </div>

    <!-- 主体布局 -->
    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：左栏整列顶到顶栏下（模式+上传按钮+
         分割线+文件树连成一张卡）；步骤条卡在右列顶部（宽度与主区等宽） -->
    <div class="itp-main-layout">
      <!-- 左侧文件管理栏 -->
      <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：模式+上传下拉经 top-actions 回本栏卡内
           顶部（与文件树连成一张卡、灰色分割线分开，类似编辑PDF） -->
      <FileSidebar
        :current-task="currentTask"
        :file-tree="fileTree"
        :selected-path="selectedPath"
        :expanded-paths="expandedPaths"
        :upload-progress="uploadProgress"
        :is-uploading="isUploading"
        :is-busy="isBusy"
        :folder-input="folderInput"
        :show-delete-confirm="showDeleteConfirm"
        @cancel-upload="cancelUpload"
        @expand-all="expandAll"
        @collapse-all="collapseAll"
        @select="handleSelect"
        @toggle="handleToggle"
        @delete="handleDelete"
        @confirm-delete="confirmDelete"
        @cancel-delete="showDeleteConfirm = false"
      >
        <template #top-actions>
          <div class="itp-sidebar-actions">
            <!-- 模式下拉（嵌入模式锁定自动模式不渲染）；处理期间与上传按钮同口径禁用
                 （isBusy=上传中/处理中/修图中/批量中/重绘中，处理中切模式会中断流程状态） -->
            <div class="itp-mode-dropdown" v-if="!isEmbedMode" @mouseenter="!isBusy && (modeMenuOpen = true)" @mouseleave="modeMenuOpen = false">
              <button type="button" class="itp-mode-select" :class="{ disabled: isBusy }" :disabled="isBusy">
                <span>{{ operationMode === 'auto' ? '自动模式' : '手动模式' }}</span>
                <AppIcon name="chevron-down" :size="13" class="itp-mode-caret" />
              </button>
              <div v-if="modeMenuOpen" class="itp-upload-menu itp-mode-menu">
                <button type="button" class="itp-upload-menu-item" :class="{ active: operationMode === 'auto' }" @click="pickMode('auto')"><AppIcon name="zap" :size="13" /> 自动模式</button>
                <button type="button" class="itp-upload-menu-item" :class="{ active: operationMode === 'manual' }" @click="pickMode('manual')"><AppIcon name="edit" :size="13" /> 手动模式</button>
              </div>
            </div>
            <!-- 上传下拉（悬停展开/菜单项触发 input click/事件链路不变） -->
            <div class="itp-upload-dropdown" @mouseenter="!isBusy && (showUploadMenu = true)" @mouseleave="showUploadMenu = false">
              <button type="button" class="itp-upload-label" :class="{ disabled: isBusy }" :disabled="isBusy">
                <AppIcon name="upload" /><span>上传</span><AppIcon name="chevron-down" :size="12" class="itp-upload-caret" />
              </button>
              <div v-if="showUploadMenu" class="itp-upload-menu">
                <button type="button" class="itp-upload-menu-item" @click="pickUploadImages"><AppIcon name="image" /> 上传图片</button>
                <button type="button" class="itp-upload-menu-item" @click="pickUploadFolder"><AppIcon name="folder" /> 上传文件夹</button>
              </div>
              <input
                type="file"
                ref="topUploadImageInput"
                multiple
                accept=".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp"
                style="display: none;"
                @change="handleImageUpload"
              />
              <input
                type="file"
                ref="topUploadFolderInput"
                webkitdirectory
                directory
                multiple
                style="display: none;"
                @change="handleFolderUpload"
              />
            </div>
          </div>
        </template>
      </FileSidebar>

      <!-- 右列：步骤条卡（顶部）+ 步骤视图（宽度与主区等宽） -->
      <div class="itp-right-column">
        <StepProgressBar
          :step-status="stepStatus"
          :is-auto-mode="operationMode === 'auto'"
          :is-processing="isBusy"
          @go-to-step="handleStepClick"
        />

        <!-- 右侧步骤视图 — 自动模式 -->
        <!-- xuechong 2026-10-11 研发BUG-0073 两口径分工：工具栏 actionsLocked=isBusy
             （上传/生成PDF/修图/批量全冻结——生成期间旋转/保存会改动正被合成的文件）；
             弹框/导航锁定=cleaningLocked（修图期间），见各弹框与守卫注释 -->
        <template v-if="operationMode === 'auto'">
        <StepImport
          v-if="currentStep === 1"
          ref="activeStepRef"
          :selected-path="selectedPath"
          :preview-url="previewUrl"
          :cleaned-preview-url="cleanedPreviewUrl"
          :is-loading-cleaned="isLoadingCleaned"
          :current-file-path="currentFilePath"
          :sibling-images="siblingImages"
          :current-image-index="currentImageIndex"
          :can-go-prev="canGoPrev"
          :can-go-next="canGoNext"
          :is-rotating="isRotating"
          :can-undo="canUndo"
          :can-redo="canRedo"
          :has-edits="hasEdits"
          :can-restore="canRestore"
          :can-single-clean="canSingleClean"
          :can-batch-clean="canBatchClean"
          :is-batch-cleaning="isBatchCleaning"
          :actions-locked="isBusy || cleaningLocked"
          v-model:add-page-number="addPageNumber"
          :show-page-toggle="!isEmbedMode"
          :image-style="imageStyle"
          :canvas-style="computedCanvasStyle"
          @prev-image="goPrevImage"
          @next-image="goNextImage"
          @rotate="rotateCurrentImage"
          @single-clean="handleSingleClean"
          @batch-clean="handleBatchClean"
          @stop-batch-clean="stopBatchClean"
          @undo="undoEdit"
          @redo="redoEdit"
          @save="saveManualEdit"
          @restore="handleRestoreImage"
          @redraw-enhance="handleRedrawEnhance"
          @redraw-weaken="handleRedrawWeaken"
          @redraw-enhance-batch="() => handleBatchRedraw('enhance')"
          @redraw-weaken-batch="() => handleBatchRedraw('weaken')"
          @redraw-settings="showRedrawSettings = true"
          @image-load="onImageLoad"
          @cleaned-image-load="onCleanedImageLoad"
          @wheel="handleWheel"
          @drag-start="startDrag"
          @drag-move="onDrag"
          @drag-end="stopDrag"
          @draw-start="startDraw"
          @draw-move="draw"
          @draw-end="stopDraw"
        />

        <StepAutoClean
          v-else-if="currentStep === 2"
          ref="activeStepRef"
          :selected-path="selectedPath"
          :preview-url="previewUrl"
          :cleaned-preview-url="cleanedPreviewUrl"
          :is-loading-cleaned="isLoadingCleaned"
          :current-file-path="currentFilePath"
          :sibling-images="siblingImages"
          :current-image-index="currentImageIndex"
          :can-go-prev="canGoPrev"
          :can-go-next="canGoNext"
          :can-batch-clean="canBatchClean"
          :is-batch-cleaning="isBatchCleaning"
          :is-rotating="isRotating"
          :can-undo="canUndo"
          :can-redo="canRedo"
          :has-edits="hasEdits"
          :can-restore="canRestore"
          :can-single-clean="canSingleClean"
          :can-advance="currentTask?.status === 'uploaded'"
          :actions-locked="isBusy || cleaningLocked"
          v-model:add-page-number="addPageNumber"
          :show-page-toggle="!isEmbedMode"
          :operation-mode="operationMode"
          :image-style="imageStyle"
          :canvas-style="computedCanvasStyle"
          @prev-image="goPrevImage"
          @next-image="goNextImage"
          @rotate="rotateCurrentImage"
          @single-clean="handleSingleClean"
          @batch-clean="handleBatchClean"
          @stop-batch-clean="stopBatchClean"
          @undo="undoEdit"
          @redo="redoEdit"
          @save="saveManualEdit"
          @restore="handleRestoreImage"
          @redraw-enhance="handleRedrawEnhance"
          @redraw-weaken="handleRedrawWeaken"
          @redraw-enhance-batch="() => handleBatchRedraw('enhance')"
          @redraw-weaken-batch="() => handleBatchRedraw('weaken')"
          @redraw-settings="showRedrawSettings = true"
          @advance-step="advanceStep"
          @image-load="onImageLoad"
          @cleaned-image-load="onCleanedImageLoad"
          @wheel="handleWheel"
          @drag-start="startDrag"
          @drag-move="onDrag"
          @drag-end="stopDrag"
          @draw-start="startDraw"
          @draw-move="draw"
          @draw-end="stopDraw"
        />

        <StepOcrAnalysis
          v-else-if="currentStep === 3"
          @skip="advanceStep"
          @auto-advance="advanceStep"
        />

        <StepGeneratePdf
          v-else-if="currentStep === 4"
          :can-process="canProcess"
          :is-processing="isProcessing"
          :show-download-btn="showDownloadBtn"
          :status-message="currentTask?.message || ''"
          :progress="currentTask?.progress || 0"
          :process-elapsed="processElapsed"
          :format-time="formatElapsedTime"
          :batch-complete-info="batchGenerateSummary"
          @generate="handleStartProcess"
          @preview-pdf="previewResult"
          @download-pdf="downloadResult"
          @edit-pdf="handleEditGeneratedPdf"
          @open-history="showHistoryModal = true"
        />
      </template>

      <!-- 右侧步骤视图 — 手动模式 -->
      <template v-else>
        <StepImport
          v-if="currentStep === 1"
          ref="activeStepRef"
          :selected-path="selectedPath"
          :preview-url="previewUrl"
          :cleaned-preview-url="cleanedPreviewUrl"
          :is-loading-cleaned="isLoadingCleaned"
          :current-file-path="currentFilePath"
          :sibling-images="siblingImages"
          :current-image-index="currentImageIndex"
          :can-go-prev="canGoPrev"
          :can-go-next="canGoNext"
          :is-rotating="isRotating"
          :can-undo="canUndo"
          :can-redo="canRedo"
          :has-edits="hasEdits"
          :can-restore="canRestore"
          :can-single-clean="canSingleClean"
          :can-batch-clean="canBatchClean"
          :is-batch-cleaning="isBatchCleaning"
          :actions-locked="isBusy || cleaningLocked"
          v-model:add-page-number="addPageNumber"
          :show-page-toggle="!isEmbedMode"
          :image-style="imageStyle"
          :canvas-style="computedCanvasStyle"
          @prev-image="goPrevImage"
          @next-image="goNextImage"
          @rotate="rotateCurrentImage"
          @single-clean="handleSingleClean"
          @batch-clean="handleBatchClean"
          @stop-batch-clean="stopBatchClean"
          @undo="undoEdit"
          @redo="redoEdit"
          @save="saveManualEdit"
          @restore="handleRestoreImage"
          @redraw-enhance="handleRedrawEnhance"
          @redraw-weaken="handleRedrawWeaken"
          @redraw-enhance-batch="() => handleBatchRedraw('enhance')"
          @redraw-weaken-batch="() => handleBatchRedraw('weaken')"
          @redraw-settings="showRedrawSettings = true"
          @image-load="onImageLoad"
          @cleaned-image-load="onCleanedImageLoad"
          @wheel="handleWheel"
          @drag-start="startDrag"
          @drag-move="onDrag"
          @drag-end="stopDrag"
          @draw-start="startDraw"
          @draw-move="draw"
          @draw-end="stopDraw"
        />

        <StepAutoClean
          v-else-if="manualActivePanel === 'clean'"
          ref="activeStepRef"
          :selected-path="selectedPath"
          :preview-url="previewUrl"
          :cleaned-preview-url="cleanedPreviewUrl"
          :is-loading-cleaned="isLoadingCleaned"
          :current-file-path="currentFilePath"
          :sibling-images="siblingImages"
          :current-image-index="currentImageIndex"
          :can-go-prev="canGoPrev"
          :can-go-next="canGoNext"
          :can-batch-clean="canBatchClean"
          :is-batch-cleaning="isBatchCleaning"
          :is-rotating="isRotating"
          :can-undo="canUndo"
          :can-redo="canRedo"
          :has-edits="hasEdits"
          :can-restore="canRestore"
          :can-single-clean="canSingleClean"
          :can-advance="false"
          :actions-locked="isBusy || cleaningLocked"
          v-model:add-page-number="addPageNumber"
          :show-page-toggle="!isEmbedMode"
          :operation-mode="operationMode"
          :image-style="imageStyle"
          :canvas-style="computedCanvasStyle"
          @prev-image="goPrevImage"
          @next-image="goNextImage"
          @rotate="rotateCurrentImage"
          @single-clean="handleSingleClean"
          @batch-clean="handleBatchClean"
          @stop-batch-clean="stopBatchClean"
          @undo="undoEdit"
          @redo="redoEdit"
          @save="saveManualEdit"
          @restore="handleRestoreImage"
          @redraw-enhance="handleRedrawEnhance"
          @redraw-weaken="handleRedrawWeaken"
          @redraw-enhance-batch="() => handleBatchRedraw('enhance')"
          @redraw-weaken-batch="() => handleBatchRedraw('weaken')"
          @redraw-settings="showRedrawSettings = true"
          @image-load="onImageLoad"
          @cleaned-image-load="onCleanedImageLoad"
          @wheel="handleWheel"
          @drag-start="startDrag"
          @drag-move="onDrag"
          @drag-end="stopDrag"
          @draw-start="startDraw"
          @draw-move="draw"
          @draw-end="stopDraw"
        />

        <StepOcrAnalysis
          v-else-if="manualActivePanel === 'ocr'"
          @skip="manualActivePanel = 'generate'"
          @auto-advance="manualActivePanel = 'generate'"
        />

        <StepGeneratePdf
          v-else-if="manualActivePanel === 'generate'"
          :can-process="canProcess"
          :is-processing="isProcessing"
          :show-download-btn="showDownloadBtn"
          :status-message="currentTask?.message || ''"
          :progress="currentTask?.progress || 0"
          :process-elapsed="processElapsed"
          :format-time="formatElapsedTime"
          :batch-complete-info="batchGenerateSummary"
          @generate="handleStartProcess"
          @preview-pdf="previewResult"
          @download-pdf="downloadResult"
          @edit-pdf="handleEditGeneratedPdf"
          @open-history="showHistoryModal = true"
        />
      </template>
      </div>
    </div>

    <!-- 底部进度/状态栏 -->
    <ProgressFooter
      :show-batch-clean-progress="showBatchCleanProgress"
      :batch-clean-status="batchCleanStatus"
      :batch-clean-elapsed="batchCleanElapsed"
      :is-processing="isProcessing"
      :process-elapsed="processElapsed"
      :show-download-btn="showDownloadBtn"
      :status-message="currentTask?.message || ''"
      :progress="currentTask?.progress || 0"
      :format-time="formatElapsedTime"
      @close-batch-clean="closeBatchCleanProgress"
      @preview-pdf="previewResult"
      @download-pdf="downloadResult"
      @close-banner="showDownloadBtn = false"
    />

    <!-- 操作记录弹窗 -->
    <!-- xuechong 2026-06-01 上传进度弹窗 -->
    <UploadModal
      :visible="showUploadModal"
      :title="uploadModalTitle"
      :folder-name="uploadModalFolderName || currentTask?.folder_name || ''"
      :total-files="uploadModalTotalFiles || currentTask?.total_files || 0"
      :percent="uploadProgress.percent"
      :current-file="uploadModalCurrentFile"
      :progress-message="uploadProgress.message"
      :phase="uploadModalPhase"
      :elapsed="uploadModalElapsed"
      @close="closeUploadModal"
      @cancel="cancelUpload"
    />

    <!-- 转换记录弹窗 -->
    <!-- xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中弹框内编辑/删除禁用（预览/下载保留） -->
    <!-- xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
         接线重命名与批量下载（均由弹框上抛，本页面统一校验、调接口、toast提示） -->
    <HistoryModal
      :visible="showHistoryModal"
      mode="download"
      :list="downloadHistory"
      :actions-locked="cleaningLocked"
      @close="showHistoryModal = false"
      @preview="handlePreviewHistory"
      @download="handleDownloadHistory"
      @edit="handleEditHistory"
      @delete="askDeleteHistoryItem"
      @rename="handleRenameHistory"
      @batch-download="handleBatchDownloadHistory"
    />

    <!-- 上传记录弹窗 -->
    <HistoryModal
      :visible="showUploadHistoryModal"
      mode="upload"
      :list="uploadHistory"
      :actions-locked="cleaningLocked"
      @close="showUploadHistoryModal = false"
      @delete-upload="askDeleteUploadHistoryItem"
      @resume-upload="handleResumeUpload"
    />

    <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
         未完成任务弹框（集中恢复入口） -->
    <!-- xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中"继续处理"禁用（重载任务会打断流程） -->
    <UnfinishedTasksModal
      v-model="showUnfinishedModal"
      :tasks="unfinishedTaskList"
      :actions-locked="cleaningLocked"
      @resume="handleResumeUnfinished"
    />

    <!-- 未保存修改提示对话框 -->
    <Transition name="ds-modal">
    <div v-if="showUnsavedWarning" class="itp-unsaved-overlay">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />未保存的修改</h4>
        <p>当前图片有未保存的修改，是否先保存？</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="cancelPendingAction"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-warning" @click="discardAndContinue"><AppIcon name="x" :size="13" /> 不保存</button>
          <button class="itp-btn itp-btn-primary" @click="saveAndContinue"><AppIcon name="save" :size="13" /> 保存并继续</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 替换确认对话框 -->
    <Transition name="ds-modal">
    <div v-if="showReplaceConfirm" class="itp-unsaved-overlay">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />替换当前文件夹</h4>
        <p>当前已有上传的文件夹，上传新文件夹将替换现有内容，是否继续？</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="cancelReplace"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-primary" @click="confirmReplace"><AppIcon name="check" :size="13" /> 确认替换</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 还原确认对话框 -->
    <Transition name="ds-modal">
    <div v-if="showRestoreConfirm" class="itp-restore-overlay">
      <div class="itp-restore-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />确认还原</h4>
        <p>确定要将此图片还原为原始状态吗？所有修图修改将丢失。</p>
        <div class="itp-restore-actions">
          <button class="itp-btn itp-btn-default" @click="showRestoreConfirm = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-warning" @click="doRestoreImage"><AppIcon name="check" :size="13" /> 确认还原</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 重绘设置弹窗 -->
    <Transition name="ds-modal">
    <div v-if="showRedrawSettings" class="itp-unsaved-overlay">
      <div class="itp-redraw-settings-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />图片重绘设置</h4>
        <div class="itp-setting-row">
          <label>调整步长（像素值）</label>
          <input type="range" min="1" max="50" v-model.number="redrawStep" />
          <span class="itp-step-value">{{ redrawStep }}</span>
        </div>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-primary" @click="showRedrawSettings = false"><AppIcon name="check" :size="13" /> 确定</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 批量PDF确认对话框 -->
    <Transition name="ds-modal">
    <div v-if="showBatchPdfModal" class="itp-batch-pdf-overlay">
      <div class="itp-batch-pdf-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />批量生成PDF</h4>
        <p>检测到 {{ batchPdfList.length }} 个子文件夹，将逐个生成PDF：</p>
        <div class="itp-batch-pdf-list">
          <div v-for="item in batchPdfList" :key="item.path" class="itp-batch-pdf-item">
            <span>{{ item.name }}</span>
            <span>{{ item.imageCount }} 张图片</span>
          </div>
        </div>
        <div class="itp-batch-pdf-actions">
          <button class="itp-btn itp-btn-default" @click="closeBatchPdfModal"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-primary" @click="startBatchPdfProcess"><AppIcon name="play" :size="13" /> 开始批量处理</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 批量PDF进度对话框 -->
    <Transition name="ds-modal">
    <div v-if="showBatchPdfProgressModal" class="itp-batch-progress-overlay">
      <div class="itp-batch-progress-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />批量处理进度</h4>
        <div class="itp-batch-progress-item">
          <div class="item-header">
            <span>总体进度: {{ batchPdfProgress.current }} / {{ batchPdfProgress.total }}</span>
            <span>当前: {{ batchPdfProgress.currentFolder }}</span>
          </div>
          <div class="itp-progress-bar">
            <div
              class="itp-progress-fill"
              :class="{ completed: batchPdfProgress.status === 'completed' }"
              :style="{ width: (batchPdfProgress.total > 0 ? (batchPdfProgress.current / batchPdfProgress.total * 100) : 0) + '%' }"
            ></div>
          </div>
        </div>
        <div class="itp-batch-progress-item">
          <div class="item-header">
            <span>当前文件夹进度</span>
            <span>{{ batchPdfProgress.currentMessage }}</span>
          </div>
          <div class="itp-progress-bar">
            <div
              class="itp-progress-fill animated"
              :style="{ width: batchPdfProgress.currentProgress + '%' }"
            ></div>
          </div>
        </div>
        <div class="itp-batch-progress-actions">
          <button
            class="itp-btn itp-btn-default"
            :disabled="isBatchPdfProcessing"
            @click="closeBatchPdfProgressModal"
          >{{ isBatchPdfProcessing ? '处理中...' : '关闭' }}</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 批量修图完成确认弹窗 -->
    <Transition name="ds-modal">
    <div v-if="showBatchCleanConfirmModal" class="itp-batch-pdf-overlay">
      <div class="itp-batch-pdf-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />批量一键修图完成</h4>
        <p style="font-size:14px; color:#333; margin:12px 0 20px;">修图已完成，是否开始生成PDF？</p>
        <div class="itp-batch-pdf-actions">
          <button class="itp-btn itp-btn-default" @click="showBatchCleanConfirmModal = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-primary" @click="handleConfirmGeneratePdf"><AppIcon name="check" :size="13" /> 确定</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：转换/上传记录删除统一站内确认弹框
         （原转换记录删除无确认直接删、上传记录用浏览器原生confirm，均不统一） -->
    <Transition name="ds-modal">
    <div v-if="historyDeleteConfirm.visible" class="itp-unsaved-overlay" style="z-index:10002;">
      <div class="itp-unsaved-dialog">
        <h4><img class="dlg-logo" src="../assets/logo-white.png" alt="" />删除记录</h4>
        <p>{{ historyDeleteConfirm.message }}</p>
        <div class="itp-unsaved-actions">
          <button class="itp-btn itp-btn-default" @click="historyDeleteConfirm.visible = false"><AppIcon name="x" :size="13" /> 取消</button>
          <button class="itp-btn itp-btn-danger" @click="confirmHistoryDelete"><AppIcon name="trash" :size="13" /> 确认删除</button>
        </div>
      </div>
    </div>
    </Transition>

    <!-- 加载遮罩 -->
    <!-- 自动模式确认弹窗 -->
    <Transition name="ds-modal">
    <div v-if="showAutoConfirm" class="auto-confirm-dialog">
      <div class="auto-confirm-card">
        <div class="auto-confirm-title"><img class="dlg-logo" src="../assets/logo-white.png" alt="" />确认切换自动模式</div>
        <p class="auto-confirm-msg">自动模式（无人值守）下系统会全程自动进行图片净化修图、OCR转换、生成PDF等完整操作，是否确认？</p>
        <div class="auto-confirm-actions">
          <button class="itp-back-btn auto-confirm-ok" @click="handleAutoConfirm"><AppIcon name="check" :size="13" /> 确定</button>
          <button class="itp-back-btn auto-confirm-cancel" @click="handleAutoCancel"><AppIcon name="x" :size="13" /> 取消</button>
        </div>
      </div>
    </div>
    </Transition>

    <div v-if="showLoading" class="global-loading-overlay">
      <div class="global-loading-content">
        <div class="global-loading-spinner"></div>
        <div class="global-loading-text">{{ loadingMessage }}</div>
      </div>
    </div>

    <!-- 隐藏的文件夹上传输入 -->
    <input
      ref="folderInput"
      type="file"
      webkitdirectory
      multiple
      style="display: none;"
      @change="handleFolderUpload"
    />
  </div>
</template>

<script>
export default { name: 'ImageToPdfPage' }
</script>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'  // xuechong 2026-06-01 添加 onMounted；xuechong 2026-09-28 添加 onUnmounted（嵌入模式轮询清理）
import { useRouter, useRoute } from 'vue-router'
import { useImageToPdf } from '../composables/useImageToPdf'
import { usePdfStore } from '../stores/pdf'
import { useToast } from '../composables/useToast'
import { getDownloadHistoryItemUrl, getPreviewHistoryItemUrl, markHistoryEdited, getUploadTask, renameDownloadHistoryItem, getDownloadHistoryBatchUrl } from '../api'
import '../styles/img-to-pdf.css'

import StepProgressBar from '../components/StepProgressBar.vue'
import FileSidebar from '../components/FileSidebar.vue'
import ProgressFooter from '../components/ProgressFooter.vue'
import HistoryModal from '../components/HistoryModal.vue'
// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 未完成任务弹框
import UnfinishedTasksModal from '../components/UnfinishedTasksModal.vue'
import UploadModal from '../components/UploadModal.vue'
import UserBadge from '../components/UserBadge.vue'
import HeaderActions from '../components/HeaderActions.vue'
// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 未完成任务按钮图标：emoji 换单色线性 SVG
import AppIcon from '../components/AppIcon.vue'
import StepImport from '../views/StepImport.vue'
import StepAutoClean from '../views/StepAutoClean.vue'
import StepOcrAnalysis from '../views/StepOcrAnalysis.vue'
import StepGeneratePdf from '../views/StepGeneratePdf.vue'

// xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐
// 上传下拉迁至步骤条行（与模式选择下拉并排）：菜单状态+隐藏input引用+菜单项触发函数，
// input 的 change 仍走原 handleImageUpload/handleFolderUpload，上传逻辑零改动
// xuechong 2026-10-10 研发BUG-0071 用户复验：模式+上传下拉再迁入左栏卡内顶部（与文件树
// 连成一张卡、灰色分割线分开，同编辑PDF结构）；模式下拉状态自 StepProgressBar 迁至本页
const showUploadMenu = ref(false)
const topUploadImageInput = ref(null)
const topUploadFolderInput = ref(null)
const modeMenuOpen = ref(false)

function pickMode(mode) {
  // xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
  // 处理期间禁用模式切换（与上传按钮同口径）：双保险——按钮已 disabled，
  // 菜单若在忙碌开始前已展开，菜单项点击在此兜底拦截
  if (isBusy.value) return
  modeMenuOpen.value = false
  handleModeChange(mode)
}

function pickUploadImages() {
  // xuechong 2026-10-11 研发BUG-0073 处理期间禁用上传（与按钮/悬停守卫同口径的菜单项兜底）
  if (isBusy.value) return
  showUploadMenu.value = false
  topUploadImageInput.value?.click()
}

function pickUploadFolder() {
  // xuechong 2026-10-11 研发BUG-0073 处理期间禁用上传（与按钮/悬停守卫同口径的菜单项兜底）
  if (isBusy.value) return
  showUploadMenu.value = false
  topUploadFolderInput.value?.click()
}

const isDev = import.meta.env.DEV
function devLog(level, ...args) { if (isDev) console[level](...args) }

const router = useRouter()
const route = useRoute()
const pdfStore = usePdfStore()
const { showToast } = useToast()

const {
  // 步骤流程
  currentStep, stepStatus,
  goToStep, advanceStep, startAutoProcess,

  // 操作模式
  operationMode, manualActivePanel,
  addPageNumber,  // xuechong 2026-10-11 研发BUG-0074-图档扫描-3.3.03 页码统一开关（按钮组复选框，默认勾选）

  // 模板引用
  folderInput, leftContainer, rightContainer,

  // 核心状态
  currentTask, fileTree, selectedPath, expandedPaths,
  previewUrl, isUploading, uploadProgress, cancelUpload, closeUploadModal,  // xuechong 2026-06-01 取消上传+弹窗
  showUploadModal, uploadModalTitle, uploadModalPhase, uploadModalCurrentFile, uploadModalElapsed, uploadModalFolderName, uploadModalTotalFiles,  // xuechong 2026-06-01 上传弹窗
  checkServerActiveTask, restoreTaskState, activeTaskList,  // xuechong 2026-06-01 状态恢复

  // 图片修图
  cleanedPreviewUrl, isLoadingCleaned, hasEdits, canRestore,
  showLoading, loadingMessage, showRestoreConfirm, currentFilePath,
  siblingImages, currentImageIndex, isRotating,

  // 未保存修改
  showUnsavedWarning,
  showReplaceConfirm,

  // 缩放/拖拽
  imageStyle,

  // 撤销/重做
  canUndo, canRedo,

  // 一键修图
  isBatchCleaning, showBatchCleanProgress, showBatchCleanConfirmModal, batchCleanStatus, batchCleanElapsed,

  // xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
  // 未完成任务（含中断）弹框数据
  unfinishedTaskList, unfinishedCount, fetchUnfinishedTasks,
  // xuechong 2026-09-30 操作记录连续失败计数（嵌入轮询降频用）
  downloadHistoryFailStreak,

  // 图片重绘
  redrawStep, showRedrawSettings,
  handleRedrawEnhance, handleRedrawWeaken, handleBatchRedraw,

  // 批量PDF
  showBatchPdfModal, showBatchPdfProgressModal, batchPdfList,
  isBatchPdfProcessing, batchPdfProgress,

  // 处理
  processElapsed, showDownloadBtn, batchGenerateSummary,
  isProcessing, isBusy, cleaningLocked, canProcess, canSingleClean, canBatchClean,
  canGoPrev, canGoNext,

  // 下载历史
  downloadHistory,
  loadDownloadHistory,
  // xuechong 2026-06-01 上传历史
  uploadHistory,
  loadUploadHistory,
  deleteUploadHistoryItem,

  // 文件树工具
  handleSelect, handleToggle, expandAll, collapseAll,

  // 文件删除
  showDeleteConfirm, handleDelete, confirmDelete,

  // 上传
  handleFolderUpload,
  handleImageUpload,

  // 图片加载
  onImageLoad, onCleanedImageLoad,

  // 缩放/拖拽
  handleWheel, startDrag, onDrag, stopDrag,

  // 绘图
  startDraw, draw, stopDraw,

  // 撤销/重做
  undoEdit, redoEdit,

  // 图片切换
  goPrevImage, goNextImage,

  // 未保存修改
  saveAndContinue, discardAndContinue, cancelPendingAction,
  confirmReplace, cancelReplace,

  // 操作包装
  handleSingleClean, handleBatchClean, handleRestoreImage, handleStartProcess,

  // 旋转
  rotateCurrentImage,

  // 保存/还原
  saveManualEdit, doRestoreImage,

  // 一键修图
  stopBatchClean,
  closeBatchCleanProgress,

  // 生成PDF
  startBatchPdfProcess, closeBatchPdfModal, closeBatchPdfProgressModal,

  // 计时器
  formatElapsedTime,

  // 下载/预览
  downloadResult, previewResult,

  // 操作记录
  deleteHistoryItem
} = useImageToPdf()

// Vue 编译器变量映射的 workaround：给 isBatchCleaning 创建别名
const batchCleaning = computed(() => isBatchCleaning.value)

// 操作记录弹窗
const showHistoryModal = ref(false)
const showUploadHistoryModal = ref(false)

// xuechong 2026-10-10 研发BUG-0071 用户复验：转换/上传记录删除统一站内确认弹框
// （kind=download 走 deleteHistoryItem(index)，kind=upload 走 deleteUploadHistoryItem(taskId)）
const historyDeleteConfirm = ref({ visible: false, kind: 'download', index: null, taskId: null, message: '' })

function askDeleteHistoryItem(index) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中禁用删除（记录弹框只留查看类）
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  const item = downloadHistory.value[index] || {}
  const name = item.folder_name || item.name || item.first_image_name || '该记录'
  historyDeleteConfirm.value = {
    visible: true, kind: 'download', index,
    message: `确定要删除记录“${name}”吗？删除后关联的PDF文件将一并清理，不可恢复。`
  }
}

function askDeleteUploadHistoryItem(taskId) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中禁用删除（记录弹框只留查看类）
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  historyDeleteConfirm.value = {
    visible: true, kind: 'upload', taskId,
    message: '确定要删除这条上传记录吗？关联的文件也将被清理。'
  }
}

async function confirmHistoryDelete() {
  const c = historyDeleteConfirm.value
  c.visible = false
  if (c.kind === 'download') {
    await deleteHistoryItem(c.index)
  } else {
    await deleteUploadHistoryItem(c.taskId)
  }
}

// 打开转换记录时加载下载历史
watch(showHistoryModal, (v) => { if (v) loadDownloadHistory() })
// 打开上传记录时加载上传历史
watch(showUploadHistoryModal, (v) => { if (v) loadUploadHistory() })

// xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成后直接弹出转换记录
// 用户决策：批量全自动完成后不再经过任何中间页面/额外点击，直接弹出转换记录供预览下载
watch(batchGenerateSummary, (v) => { if (v) showHistoryModal.value = true })

// 自动模式确认弹窗
const showAutoConfirm = ref(false)
// xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 嵌入模式（form-in嵌入页带embed=1进入）锁定自动模式：模式下拉框隐藏、切换请求一律不生效，
// 页面全程保持无人值守自动模式；普通直连无ds_embed_mode标记，模式切换与从前完全一致
const isEmbedMode = sessionStorage.getItem('ds_embed_mode') === '1'

function handleModeChange(val) {
  // 嵌入模式锁定自动模式：不响应任何切往手动模式的请求（下拉框已隐藏，此处双保险）
  if (isEmbedMode) return
  if (val === 'manual') {
      operationMode.value = 'manual'
    return
  }
  // 切换到自动模式
  if (currentTask.value) {
    // 已上传图片，弹出确认
    showAutoConfirm.value = true
  } else {
    // 未上传图片，直接进入自动模式
    operationMode.value = 'auto'
    }
}

function handleAutoConfirm() {
  showAutoConfirm.value = false
  operationMode.value = 'auto'
  startAutoProcess()
}

function handleAutoCancel() {
  showAutoConfirm.value = false
  operationMode.value = 'manual'
}

// 当前活动步骤组件的引用
const activeStepRef = ref(null)

// 连接子组件暴露的模板引用到 composable（drag/zoom 用）
watch(activeStepRef, (comp) => {
  if (comp) {
    nextTick(() => {
      if (comp.previewPanel) {
        const pp = comp.previewPanel
        if (pp.leftContainerRef) leftContainer.value = pp.leftContainerRef
        if (pp.rightContainerRef) rightContainer.value = pp.rightContainerRef
      }
    })
  }
}, { immediate: true })

// canvas 样式：步骤2的编辑面板启用绘图
const isEditingStep = computed(() => {
  if (operationMode.value === 'auto') return currentStep.value === 2
  return manualActivePanel.value === 'clean' && currentStep.value > 1
})
const computedCanvasStyle = computed(() => {
  const base = imageStyle.value
  const centeredBase = { ...base, transform: `translate(-50%, -50%) ${base.transform || ''}` }
  return isEditingStep.value ? { ...centeredBase, pointerEvents: 'auto', cursor: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'20\' height=\'20\' viewBox=\'0 0 20 20\'%3E%3Crect x=\'2\' y=\'2\' width=\'16\' height=\'16\' fill=\'white\' stroke=\'%23333\' stroke-width=\'2\'/%3E%3C/svg%3E") 10 10, crosshair' } : centeredBase
})

// 步骤条点击处理
function handleStepClick(stepNum) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：处理中步骤条锁定
  // （步骤条 clickable 类已随 isProcessing 摘除，此处兜底拦截）
  if (cleaningLocked.value) return
  if (stepNum === 1) return
  if (stepNum === 3) stepNum = 4  // OCR步骤已移除，重定向到生成PDF

  // 更新步骤状态（让三角指示器显示）
  const newStatus = { ...stepStatus.value }
  for (const s of [1, 2, 4]) {
    if (s < stepNum) newStatus[s] = 'completed'
    else if (s === stepNum) newStatus[s] = 'active'
    else newStatus[s] = 'pending'
  }
  stepStatus.value = newStatus

  if (operationMode.value === 'manual') {
    // 手动模式：同时切换步骤和工具面板
    currentStep.value = stepNum
    if (stepNum === 2) {
      manualActivePanel.value = 'clean'
    } else if (stepNum === 4) {
      manualActivePanel.value = 'generate'
    }
  } else {
    // 自动模式：切换到对应步骤视图
    currentStep.value = stepNum
  }
}

// 批量修图完成确认弹窗：点击"确定"后切换到生成PDF页面并自动开始生成
function handleConfirmGeneratePdf() {
  showBatchCleanConfirmModal.value = false
  // 切换到步骤4（生成PDF）
  if (operationMode.value === 'manual') {
    manualActivePanel.value = 'generate'
  } else {
    currentStep.value = 4
  }
  // 自动开始生成PDF
  handleStartProcess()
}

// 操作记录：预览/下载
function handlePreviewHistory(index) {
  const url = getPreviewHistoryItemUrl(index)
  window.open(url, '_blank')
}

function handleDownloadHistory(index) {
  const url = getDownloadHistoryItemUrl(index)
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 即时更新下载次数
  if (downloadHistory.value[index]) {
    downloadHistory.value[index].download_count = (downloadHistory.value[index].download_count || 0) + 1
  }
}

// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 转换记录重命名：前端先做非空/非法字符校验并剥掉.pdf后缀，再调后端既有rename接口
// （只改记录显示名，下载文件名随之变化，物理PDF不动），成功后同步本地列表
async function handleRenameHistory(index, newName) {
  const item = downloadHistory.value[index]
  if (!item) {
    showToast('记录不存在', 'error')
    return
  }
  const trimmed = String(newName || '').trim()
  if (!trimmed) {
    showToast('文件名不能为空', 'warning')
    return
  }
  // 与后端rename接口同一份非法字符清单，逐字符检查（/ \ < > : " | ? *）
  const invalidChars = '/\\<>:"|?*'
  for (const ch of invalidChars) {
    if (trimmed.includes(ch)) {
      showToast('文件名不能包含 / \\ < > : " | ? * 这些字符', 'warning')
      return
    }
  }
  // 用户带了.pdf后缀时剥掉再提交（下载文件名由后端自动补.pdf，避免下载出xxx.pdf.pdf）
  let baseName = trimmed
  if (trimmed.toLowerCase().endsWith('.pdf')) {
    baseName = trimmed.slice(0, -4)
  }
  // 剥掉后缀后再去一次首尾空格（如"abc .pdf"剥后尾随空格），空了（如只输".pdf"）直接拦截
  baseName = baseName.trim()
  if (!baseName) {
    showToast('文件名不能为空', 'warning')
    return
  }
  try {
    await renameDownloadHistoryItem(index, baseName)
    item.folder_name = baseName
    item.first_image_name = baseName
    showToast('重命名成功', 'success')
  } catch (err) {
    const detail = err?.response?.data?.detail
    showToast(detail || '重命名失败，请重试', 'error')
  }
}

// xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
// 批量下载：弹框上抛勾选记录的全局索引列表，走后端批量ZIP接口一次下载；
// 与单条下载同款a标签直链方式，成功发起后本地即时累加下载次数
function handleBatchDownloadHistory(indices) {
  if (!Array.isArray(indices) || indices.length === 0) {
    showToast('未指定要下载的记录', 'warning')
    return
  }
  const url = getDownloadHistoryBatchUrl(indices)
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 即时更新下载次数（后端打包成功会计次，这里前端同步展示）
  indices.forEach(i => {
    if (downloadHistory.value[i]) {
      downloadHistory.value[i].download_count = (downloadHistory.value[i].download_count || 0) + 1
    }
  })
}

// 操作记录：编辑
async function handleEditHistory(index) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中跳转编辑PDF会中断流程，禁用
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  const item = downloadHistory.value[index]
  if (!item) {
    showToast('记录不存在', 'error')
    return
  }
  // 后台标记为已编辑（不阻塞导航）
  markHistoryEdited(index).then(() => {
    item.edited = true
  }).catch(err => {
    devLog('error', '[编辑记录] 标记失败:', err)
  })

  pdfStore.setPendingEdit({
    source: 'img-to-pdf',
    history_index: index,
    task_id: item.task_id,
    fileName: item.first_image_name || item.folder_name || '未命名'
  })
  showHistoryModal.value = false
  await nextTick()
  router.push('/edit-pdf')
}

// 返回首页
// xuechong 2026-06-03 从上传记录恢复任务
async function handleResumeUpload(taskId) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中恢复上传会重载任务打断流程，禁用
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  showUploadHistoryModal.value = false
  sessionStorage.setItem('ds_current_task_id', taskId)
  const activeTask = await checkServerActiveTask()
  if (activeTask && activeTask.task_id === taskId) {
    await restoreTaskState(activeTask)
  } else {
    // 任务在服务器上可能已不存在（重启后丢失），尝试直接加载
    try {
      const res = await getUploadTask(taskId)
      if (res.data && res.data.task_id) {
        await restoreTaskState(res.data)
      }
    } catch (e) {
      showToast('该任务已过期（服务器重启后任务数据会清空），请重新上传', 'warning')
    }
  }
}

function handleBack() {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：一键修图/批量修图进行中禁用返回首页
  // （页面切走后修图循环仍在后台跑，结果无人可见＝乱套）
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再离开', 'warning')
    return
  }
  if (hasEdits.value) {
    showUnsavedWarning.value = true
    return
  }
  router.push('/')
}

// 跳转编辑PDF
function handleEditGeneratedPdf() {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中跳转编辑PDF会中断流程，禁用
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  if (!currentTask.value) {
    showToast('没有可编辑的PDF', 'warning')
    return
  }
  pdfStore.setPendingEdit({
    source: 'img-to-pdf',
    task_id: currentTask.value.task_id,
    fileName: currentTask.value.folder_name || '未命名'
  })
  router.push('/edit-pdf')
}

// xuechong 2026-06-01 页面挂载时尝试恢复之前的任务状态
// xuechong 2026-06-02 页面挂载时恢复任务（支持多任务）
// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 重构：进入页面不再自动恢复上次任务（用户要求
// "每次进入老实显示首页、文件列表空着"），仅刷新未完成任务徽标；恢复改为弹框内用户主动选择
onMounted(async () => {
  await fetchUnfinishedTasks()
  // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
  // 嵌入模式（form-in嵌入页带embed=1进入）下每1秒自动刷新三处列表数据：
  // 未完成任务徽标计数、上传记录弹框、转换记录——form-in智能收集整理页上传/处理后，
  // 本页1秒内自动出现对应条目；页面切到后台时本轮跳过（省请求），普通直接访问不启轮询。
  // 发现新上传的未完成任务时自动把它载入工作区并弹提示（页面空闲才动作，不打断进行中的操作），
  // 让嵌入页对 form-in 侧的上传有肉眼可见的反应；首轮只记录现状不动作（打开页面不抢载历史任务）
  if (sessionStorage.getItem('ds_embed_mode') === '1') {
    // 嵌入模式默认自动模式（无人值守）：不弹确认框直接切自动，页首模式框显示"自动模式"；
    // 普通直接访问仍默认手动模式，行为与从前完全一致
    operationMode.value = 'auto'
    embedPollTimer = setInterval(embedPollTick, 1000)
  }
})

// xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 嵌入模式轮询单轮：刷新列表数据 + 检测新任务自动载入（防上一轮未完成时重入）
// xuechong 2026-09-30 同需求追加：连续失败降频——操作记录连续失败达3次（服务异常/登录态失效等）
// 时不再每秒轮询轰炸接口与提示，改为每15秒探活一次，任一次加载成功即自动恢复正常轮询节奏
let embedPollLastProbeAt = 0

async function embedPollTick() {
  if (document.hidden) {
    return
  }
  if (embedPollRunning) {
    return
  }
  if (downloadHistoryFailStreak.value >= 3) {
    const nowMs = Date.now()
    if (nowMs - embedPollLastProbeAt < 15000) {
      return
    }
    embedPollLastProbeAt = nowMs
  }
  embedPollRunning = true
  try {
    await fetchUnfinishedTasks()
    loadUploadHistory()
    loadDownloadHistory()
    const taskList = unfinishedTaskList.value || []
    const idList = taskList.map(t => t.task_id)
    const newestTask = taskList[0]
    // 首轮：自动载入最新的未完成任务（用户在form-in上传后首次打开本页也能立刻看到文件）；
    // 之后各轮：出现更新的任务才自动载入。本页只做展示与手动操作——自动净化修图/生成PDF由
    // form-in智能收集整理页驱动（确认框点"是"立即执行），与是否打开本页无关，避免两处抢着处理
    if (embedKnownTaskIds === null) {
      if (!isBusy.value && !isProcessing.value) {
        if (newestTask) {
          await restoreTaskState(newestTask)
          showToast('已载入最新任务：' + (newestTask.folder_name || newestTask.task_id))
        } else {
          // 没有未完成任务时载入最新任务（含已处理完成的），首次打开也能看到刚处理完的文件与成品
          const latestTask = await checkServerActiveTask()
          if (latestTask) {
            await restoreTaskState(latestTask)
          }
        }
      }
      embedKnownTaskIds = idList
      return
    }
    const isNewTask = newestTask && !embedKnownTaskIds.includes(newestTask.task_id)
    // xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    // 新任务就是本页当前任务（本页自己刚上传的）或页面正忙时不抢载——抢载会重置文件树与步骤，
    // 把本页自动链（修图→生成PDF）打断成"请选择要处理的目录"失败；
    // 只自动载入真正来自外部（form-in八步页上传等）的新任务
    const sameAsCurrent = currentTask.value && newestTask && newestTask.task_id === currentTask.value.task_id
    if (isNewTask && !sameAsCurrent && !isBusy.value && !isProcessing.value) {
      await restoreTaskState(newestTask)
      showToast('发现新上传任务，已自动载入：' + (newestTask.folder_name || newestTask.task_id))
    }
    embedKnownTaskIds = idList
  } finally {
    embedPollRunning = false
  }
}

onUnmounted(() => {
  if (embedPollTimer) {
    clearInterval(embedPollTimer)
    embedPollTimer = null
  }
})

// xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
// 未完成任务弹框交互
const showUnfinishedModal = ref(false)
// xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
// 嵌入模式列表自动刷新定时器与状态（句柄在onUnmounted清理；knownIds首轮只记录，running防重入）
let embedPollTimer = null
let embedPollRunning = false
let embedKnownTaskIds = null

async function openUnfinishedModal() {
  await fetchUnfinishedTasks()
  showUnfinishedModal.value = true
}

async function handleResumeUnfinished(task) {
  // xuechong 2026-10-11 研发BUG-0073 修图锁定：修图进行中恢复任务会重载任务树打断流程，禁用
  // （弹框内按钮已随 actionsLocked 禁用，此处兜底）
  if (cleaningLocked.value) {
    showToast('正在修图中，请等待处理完成后再操作', 'warning')
    return
  }
  showUnfinishedModal.value = false
  await restoreTaskState(task)
  await fetchUnfinishedTasks()
}
</script>

<style scoped>
/* xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化 */
/* 未完成任务按钮徽标 */
.itp-unfinished-btn { position: relative; }
.itp-unfinished-badge {
  display: inline-block;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: 9px;
  background: #ff4d4f;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}
</style>
