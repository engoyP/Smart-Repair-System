<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">{{ isNew ? '新增知识' : '知识详情（只读）' }}</h2>
    </div>

    <el-card shadow="never">
      <el-form :model="form" label-width="100px" style="max-width: 800px" :disabled="!isNew">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="知识标题/故障现象描述" />
        </el-form-item>
        <el-form-item label="故障码">
          <el-input v-model="form.fault_code" placeholder="如 TEMP_HIGH_001" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category_id" clearable filterable placeholder="选择分类（参考用）" style="width: 100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="故障标签">
          <el-select v-model="form.fault_tags" multiple filterable allow-create placeholder="输入故障标签，回车添加" style="width: 100%" />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="form.device_type" clearable filterable placeholder="选择适用设备类型" style="width: 100%">
            <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="紧急程度">
          <el-select v-model="form.severity" style="width: 100%">
            <el-option label="低" value="LOW" />
            <el-option label="中" value="MEDIUM" />
            <el-option label="高" value="HIGH" />
            <el-option label="紧急" value="CRITICAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input v-model="form.content" type="textarea" :rows="8" placeholder="知识内容，包含排查步骤、处理方法等" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="草稿" value="DRAFT" />
            <el-option label="审核中" value="UNDER_REVIEW" />
            <el-option label="已发布" value="PUBLISHED" />
            <el-option label="已过期" value="DEPRECATED" />
            <el-option label="已归档" value="ARCHIVED" />
          </el-select>
        </el-form-item>
      </el-form>
      <!-- 操作按钮放在表单外：el-form 的 disabled（只读态）会级联禁用内部按钮 -->
      <div class="form-actions">
        <el-button v-if="isNew" type="primary" @click="handleSave" :loading="saving">保存</el-button>
        <el-button @click="goBack">返回</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../api'

const route = useRoute()
const router = useRouter()
const isNew = computed(() => !route.params.id || route.params.id === 'new')
const saving = ref(false)
const categories = ref([])

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}
const deviceTypeOptions = ref([])

const form = ref({
  title: '',
  fault_code: '',
  category_id: null,
  device_type: '',
  severity: 'LOW',
  fault_tags: [],
  content: '',
  status: 'DRAFT'
})

const loadCategories = async () => {
  const res = await request.get('/categories/', { params: { page_size: 1000, category_type: 'KNOWLEDGE_TYPE' } })
  // 后端返回树形结构，展平为下拉选项
  const flatten = (nodes, result = []) => {
    for (const node of nodes) {
      result.push({ id: node.id, name: node.name })
      if (node.children && node.children.length > 0) {
        flatten(node.children, result)
      }
    }
    return result
  }
  categories.value = flatten(res.items || [])
}

const loadData = async () => {
  if (isNew.value) return
  const res = await request.get(`/knowledge/${route.params.id}`)
  Object.assign(form.value, res)
}

const handleSave = async () => {
  if (!isNew.value) {
    ElMessage.warning('知识库为只读，禁止修改知识条目')
    return
  }
  saving.value = true
  try {
    // 过滤掉后端不支持的字段
    const { category_id, severity, ...backendData } = form.value
    await request.post('/knowledge/', { ...backendData, fault_tags: form.value.fault_tags || [] })
    ElMessage.success('创建成功')
    router.push('/knowledge')
  } finally { saving.value = false }
}

const goBack = () => {
  // 有历史记录则返回上一页，否则兜底回知识列表（避免直接访问详情页时 back 无效）
  if (window.history.state.back) {
    router.back()
  } else {
    router.push('/knowledge/list')
  }
}

onMounted(async () => {
  await loadCategories()
  try {
    const res = await request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    deviceTypeOptions.value = flattenTree(res.items || [])
  } catch { /* ignore */ }
  if (!isNew.value) await loadData()
})
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.form-actions { max-width: 800px; padding-left: 100px; margin-top: 8px; }
</style>