<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">分类管理</h2>
      <el-button type="primary" @click="handleAdd">新增分类</el-button>
    </div>

    <el-card shadow="never">
      <div class="filter-bar">
        <el-select v-model="typeFilter" placeholder="分类类型" class="filter-select" @change="fetchData">
          <el-option label="设备类型" value="DEVICE_TYPE" />
          <el-option label="故障类型" value="FAULT_TYPE" />
          <el-option label="知识类型" value="KNOWLEDGE_TYPE" />
        </el-select>
        <el-button class="action-btn secondary-btn" @click="expandAll">全部展开</el-button>
        <el-button class="action-btn secondary-btn" @click="collapseAll">全部收起</el-button>
      </div>

      <el-table
        :data="treeList"
        v-loading="loading"
        row-key="id"
        :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
        default-expand-all
        stripe
        style="margin-top: 16px"
      >
        <el-table-column prop="name" label="分类名称" min-width="200" />
        <el-table-column prop="code" label="分类编码" width="180" />
        <el-table-column prop="sort_order" label="排序" width="80" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" type="primary" @click="handleAddChild(row)">添加子级</el-button>
              <el-button size="small" type="primary" @click="handleEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog :title="dialogTitle" v-model="dialogVisible" width="500px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="分类名称" required>
          <el-input v-model="form.name" placeholder="分类名称" />
        </el-form-item>
        <el-form-item label="分类编码" required>
          <el-input v-model="form.code" placeholder="唯一编码" />
        </el-form-item>
        <el-form-item label="分类类型" required>
          <el-select v-model="form.category_type" style="width: 100%" :disabled="!!editingId">
            <el-option label="设备类型" value="DEVICE_TYPE" />
            <el-option label="故障类型" value="FAULT_TYPE" />
            <el-option label="知识类型" value="KNOWLEDGE_TYPE" />
          </el-select>
        </el-form-item>
        <el-form-item label="父级分类">
          <el-select v-model="form.parent_id" clearable placeholder="不选则为顶级" style="width: 100%">
            <el-option v-for="c in flatCategories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="分类描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const treeList = ref([])
const flatCategories = ref([])
const loading = ref(false)
const typeFilter = ref('DEVICE_TYPE')
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)

const form = ref({
  name: '', code: '', category_type: 'DEVICE_TYPE', parent_id: null, sort_order: 0, description: ''
})

const dialogTitle = computed(() => {
  if (editingId.value) return '编辑分类'
  if (form.value.parent_id) return '添加子分类'
  return '新增分类'
})

// 展平树结构为下拉选项（递归）
const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push(node)
    if (node.children && node.children.length > 0) {
      flattenTree(node.children, result)
    }
  }
  return result
}

const fetchData = async () => {
  loading.value = true
  try {
    const res = await request.get('/categories/', { params: { page_size: 1000, category_type: typeFilter.value } })
    // 后端返回树形结构 { items: [...], total: N }
    treeList.value = res.items || []
    flatCategories.value = flattenTree(res.items || [])
  } catch { /* handled */ }
  finally { loading.value = false }
}

const resetForm = () => {
  editingId.value = null
  form.value = {
    name: '', code: '', category_type: typeFilter.value, parent_id: null, sort_order: 0, description: ''
  }
}

const handleAdd = () => { resetForm(); dialogVisible.value = true }
const handleAddChild = (row) => { resetForm(); form.value.parent_id = row.id; form.value.category_type = row.category_type; dialogVisible.value = true }
const handleEdit = (row) => { editingId.value = row.id; Object.assign(form.value, row); dialogVisible.value = true }

const handleSave = async () => {
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/categories/${editingId.value}`, form.value)
      ElMessage.success('更新成功')
    } else {
      await request.post('/categories/', form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchData()
  } finally { saving.value = false }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除该分类？子分类也将被删除。', '删除确认', { type: 'warning' })
    await request.delete(`/categories/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch { /* cancelled */ }
}

const expandAll = () => {
  // Element Plus table tree expand all is managed via default-expand-all
  fetchData()
}
const collapseAll = () => {
  // For simplicity, refetch without expand
  fetchData()
}

onMounted(fetchData)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.filter-bar { display: flex; gap: 12px; align-items: center; }
</style>