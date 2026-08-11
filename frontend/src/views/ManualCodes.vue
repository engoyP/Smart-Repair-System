<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">设备手册错误码</h2>
        <span class="page-desc">从设备说明书导入的「错误码 → 故障诊断」权威映射（含出处），供 AI 问答检索引用</span>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="fetchData">刷新</el-button>
      </div>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索错误码 / 标题 / 手册名"
          clearable
          class="filter-input"
          @clear="handleSearch"
          @keyup.enter="handleSearch"
        />
        <el-select v-model="deviceTypeFilter" placeholder="设备类型" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="dt in deviceTypes" :key="dt" :label="dt" :value="dt" />
        </el-select>
        <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
        <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" size="default">
        <el-table-column label="错误码" width="120">
          <template #default="{ row }">
            <span class="err-code">{{ row.error_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="device_type" label="设备类型" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.device_type" size="small" type="success" effect="plain">{{ row.device_type }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="manual_name" label="手册名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="chapter" label="章节" width="130" show-overflow-tooltip />
        <el-table-column prop="page" label="页码" width="80" />
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="showDetail(row)">查看</el-button>
            <el-button v-if="isAdmin" size="small" type="danger" :loading="row._deleting" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchData"
        />
      </div>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailDialog.visible" :title="detailDialog.item?.title" width="680px" destroy-on-close>
      <template v-if="detailDialog.item">
        <div class="detail-meta">
          <span class="err-code-lg">{{ detailDialog.item.error_code }}</span>
          <el-tag v-if="detailDialog.item.device_type" size="small" type="success" effect="plain">{{ detailDialog.item.device_type }}</el-tag>
        </div>
        <div class="detail-cite">
          <div class="cite-row"><span class="cite-label">手册</span>{{ detailDialog.item.manual_name }}</div>
          <div class="cite-row"><span class="cite-label">章节</span>{{ detailDialog.item.chapter }}</div>
          <div class="cite-row"><span class="cite-label">页码</span>{{ detailDialog.item.page }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-label">错误含义 / 触发条件</div>
          <div class="detail-content">{{ detailDialog.item.description }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-label">可能原因</div>
          <div class="detail-content">{{ detailDialog.item.causes || '未收录' }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-label">处理步骤 / 排查方向</div>
          <div class="detail-content">{{ detailDialog.item.solutions || '未收录' }}</div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'
import dayjs from 'dayjs'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const deviceTypeFilter = ref('')
const deviceTypes = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const detailDialog = reactive({ visible: false, item: null })

const currentUser = JSON.parse(localStorage.getItem('current_user') || '{}')
const isAdmin = computed(() => currentUser.role === 'ADMIN')

const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (deviceTypeFilter.value) params.device_type = deviceTypeFilter.value
    const res = await request.get('/manual-codes/', { params })
    list.value = res.items
    total.value = res.total
  } catch { /* handled */ }
  finally { loading.value = false }
}

const loadDeviceTypes = async () => {
  try {
    const res = await request.get('/manual-codes/', { params: { page: 1, page_size: 100 } })
    deviceTypes.value = [...new Set(res.items.map(i => i.device_type).filter(Boolean))]
  } catch { /* handled */ }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; deviceTypeFilter.value = ''; page.value = 1; fetchData() }

const showDetail = (row) => {
  detailDialog.item = row
  detailDialog.visible = true
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除手册条目「${row.error_code} - ${row.title}」吗？删除后 AI 检索将不再引用该错误码。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  row._deleting = true
  try {
    await request.delete(`/manual-codes/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch { /* handled */ }
  finally { row._deleting = false }
}

onMounted(() => {
  fetchData()
  loadDeviceTypes()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-left { display: flex; align-items: baseline; gap: 12px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.page-desc { font-size: 12px; color: var(--color-text-tertiary); }
.header-actions { display: flex; gap: 12px; }

.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 240px; }
.filter-select { width: 160px; }
.action-btn { flex-shrink: 0; }

.table-card { padding: 4px 8px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }

.err-code {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  font-family: Consolas, Monaco, monospace;
  color: #F56C6C;
  background: #FFF0F0;
  border: 1px solid #FFD3D3;
  padding: 2px 8px;
  border-radius: 4px;
}
.err-code-lg {
  display: inline-block;
  font-size: 16px;
  font-weight: 700;
  font-family: Consolas, Monaco, monospace;
  color: #F56C6C;
  background: #FFF0F0;
  border: 1px solid #FFD3D3;
  padding: 3px 12px;
  border-radius: 6px;
}
.detail-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.detail-cite {
  padding: 10px 14px;
  background: #FFF3E8;
  border: 1px solid #FFD8B5;
  border-radius: 8px;
  font-size: 13px;
  color: #B25000;
  margin-bottom: 16px;
}
.cite-row { display: flex; align-items: baseline; gap: 10px; line-height: 1.9; }
.cite-label { flex-shrink: 0; width: 48px; font-weight: 600; color: #FF7D00; }
.detail-block { margin-bottom: 16px; }
.detail-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.detail-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  background: var(--color-bg-page);
  border-radius: 6px;
  padding: 10px 12px;
}
</style>
