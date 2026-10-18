<template>
  <div class="itp-right-panel">
    <div class="itp-review-module">
      <div class="itp-module-title">分析结果复核</div>

      <div class="itp-review-item">
        <label class="itp-review-label">建议PDF文件名</label>
        <input
          type="text"
          class="itp-review-input"
          style="min-height: auto;"
          v-model="localData.filename"
          placeholder="请输入PDF文件名..."
        />
      </div>

      <div class="itp-review-item">
        <label class="itp-review-label">文档摘要</label>
        <textarea
          class="itp-review-input"
          v-model="localData.summary"
          placeholder="请输入文档摘要..."
        ></textarea>
      </div>

      <div class="itp-review-item">
        <label class="itp-review-label">元数据信息</label>
        <div class="itp-metadata-grid">
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">文档类型</label>
            <input type="text" class="itp-metadata-input" v-model="localData.docType" placeholder="如：设备清单" />
          </div>
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">创建日期</label>
            <input type="text" class="itp-metadata-input" v-model="localData.createDate" placeholder="YYYY-MM-DD" />
          </div>
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">关键词</label>
            <input type="text" class="itp-metadata-input" v-model="localData.keywords" placeholder="关键词，逗号分隔" />
          </div>
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">PDF格式</label>
            <select class="itp-metadata-input" v-model="localData.pdfFormat">
              <option value="PDF/A">可搜索PDF（双层）</option>
              <option value="image">仅图片PDF</option>
              <option value="compressed">压缩PDF</option>
            </select>
          </div>
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">保存路径</label>
            <input type="text" class="itp-metadata-input" v-model="localData.savePath" placeholder="保存路径" />
          </div>
          <div class="itp-metadata-item">
            <label class="itp-metadata-label">归档分类</label>
            <select class="itp-metadata-input" v-model="localData.archiveCategory">
              <option value="equipment">设备资料</option>
              <option value="finance">财务类</option>
              <option value="hr">人事类</option>
              <option value="contract">合同类</option>
              <option value="other">其他</option>
            </select>
          </div>
        </div>
      </div>

      <div class="itp-review-actions">
        <button class="itp-btn itp-btn-default" @click="$emit('reprocess')"><AppIcon name="refresh-cw" :size="13" /> 重新处理</button>
        <button class="itp-btn itp-btn-primary" @click="$emit('confirm')"><AppIcon name="check" :size="13" /> 确认归档</button>
      </div>
    </div>
  </div>
</template>

<script setup>
// xuechong 2026-10-10 研发BUG-0071 用户复验：按钮补图标
import AppIcon from '../components/AppIcon.vue'
import { reactive, watch } from 'vue'

const props = defineProps({
  reviewData: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['reprocess', 'confirm', 'update:reviewData'])

const localData = reactive({ ...props.reviewData })

watch(localData, (val) => {
  emit('update:reviewData', { ...val })
}, { deep: true })

watch(() => props.reviewData, (val) => {
  Object.assign(localData, val)
}, { deep: true })
</script>
