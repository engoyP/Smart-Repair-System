<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">维修报表</h2>
      <el-button type="primary" @click="$router.push('/work-orders/new')">新建工单</el-button>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索工单编号/故障描述" clearable class="filter-input" @clear="handleSearch" @keyup.enter="handleSearch" />
        <el-select v-model="statusFilter" placeholder="工单状态" clearable class="filter-select" @change="handleSearch">
          <el-option label="草稿" value="DRAFT" />
          <el-option label="维修中" value="IN_PROGRESS" />
          <el-option label="待归档" value="ARCHIVING" />
          <el-option label="已归档" value="ARCHIVED" />
          <el-option label="已完成" value="COMPLETED" />
        </el-select>
        <el-select v-model="deviceTypeFilter" placeholder="设备类型" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="filter-date"
          @change="handleSearch"
          clearable
        />
        <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
        <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
      </div>
    </el-card>

    <el-card class="table-card" shadow="never">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column prop="work_order_no" label="工单编号" width="170" />
        <el-table-column prop="fault_description" label="故障描述" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="status-tag" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="480" fixed="right">
          <template #default="{ row }">
            <div class="col-actions">
              <div class="action-row">
                <el-button size="small" type="primary" @click="$router.push(`/work-orders/${row.id}`)">查看</el-button>
                <el-button v-if="!isSupervisor" size="small" type="warning" :disabled="['COMPLETED', 'ARCHIVED'].includes(row.status) || (!isCreatedByMe(row) && !isAdmin && !isAssignedTech(row))" @click="$router.push(`/work-orders/${row.id}?edit=1`)">编辑</el-button>
                <el-button v-if="!isSupervisor" size="small" type="danger" :disabled="['COMPLETED', 'ARCHIVED'].includes(row.status) || (!isCreatedByMe(row) && !isAdmin)" @click="handleDelete(row)">删除</el-button>
              </div>
              <div class="action-row progress-row" v-if="canOperateProgress(row)">
                <el-button
                  v-if="row.status === 'ASSIGNED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_ACCEPTED`]"
                  @click="handleTransition(row, 'ACCEPTED')"
                >接受任务</el-button>
                <el-button
                  v-if="row.status === 'ACCEPTED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_ARRIVED`]"
                  @click="handleTransition(row, 'ARRIVED')"
                >已到达现场</el-button>
                <el-button
                  v-if="row.status === 'ARRIVED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_INSPECTING`]"
                  @click="handleTransition(row, 'INSPECTING')"
                >开始检查</el-button>
                <el-button
                  v-if="row.status === 'INSPECTING'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_IN_PROGRESS`]"
                  @click="handleTransition(row, 'IN_PROGRESS')"
                >开始维修</el-button>
                <el-button
                  v-if="row.status === 'IN_PROGRESS'"
                  size="small"
                  type="success"
                  :loading="transitionLoading[`${row.id}_ARCHIVING`]"
                  @click="handleFinishRepair(row)"
                >完成维修</el-button>
                <el-button
                  v-if="row.status === 'ARCHIVING'"
                  size="small"
                  type="primary"
                  @click="$router.push(`/work-orders/${row.id}?edit=1`)"
                >去归档</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchData"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'
import { workOrderTransition } from '../api/supervisor'
import dayjs from 'dayjs'

const router = useRouter()

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}
const deviceTypeOptions = ref([])

// 当前登录用户（用于权限判断：仅创建者或管理员可编辑）
const currentUser = (() => {
  try {
    const raw = localStorage.getItem('current_user')
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
})()
const isAdmin = currentUser.role === 'ADMIN'
const isSupervisor = currentUser.role === 'SUPERVISOR' || isAdmin
const isCreatedByMe = (row) => {
  if (row.created_by_employee_id && currentUser.employee_id) {
    return row.created_by_employee_id === currentUser.employee_id
  }
  return !!row.created_by && row.created_by === currentUser.id
}
const isAssignedTech = (row) => {
  const tid = row.technician_id || row.assigned_technician_id
  if (!tid) return false
  return tid === currentUser.id
}
const canOperateProgress = (row) => isAssignedTech(row)
const transitionLoading = ref({})

const handleTransition = async (row, toStatus, source = 'TECH_PROGRESS') => {
  try {
    transitionLoading.value[`${row.id}_${toStatus}`] = true
    await workOrderTransition(row.id, {
      to_status: toStatus,
      source,
      remark: undefined,
    })
    await fetchData()
  } catch {
    // handled
  } finally {
    transitionLoading.value[`${row.id}_${toStatus}`] = false
  }
}

const handleFinishRepair = async (row) => {
  await handleTransition(row, 'ARCHIVING')
  router.push(`/work-orders/${row.id}?edit=1`)
}

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const deviceTypeFilter = ref('')
const dateRange = ref(null)
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

const statusMap = {
  DRAFT: '草稿',
  SUBMITTED: '待派工',
  ASSIGNED: '已派单',
  ACCEPTED: '已接单',
  ARRIVED: '已到达',
  INSPECTING: '检查中',
  IN_PROGRESS: '维修中',
  ARCHIVING: '待归档',
  ARCHIVED: '已归档',
  COMPLETED: '已完成',
  REJECTED: '已退回',
}

const statusLabel = (s) => statusMap[s] || s
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const STORAGE_KEY = 'workorders_filter'

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (statusFilter.value) params.status = statusFilter.value
    if (deviceTypeFilter.value) params.device_type = deviceTypeFilter.value
    if (dateRange.value) {
      params.date_from = dayjs(dateRange.value[0]).format('YYYY-MM-DD')
      params.date_to = dayjs(dateRange.value[1]).format('YYYY-MM-DD')
    }
    const res = await request.get('/work-orders/', { params })
    list.value = res.items
    total.value = res.total

    // 保存筛选条件到 sessionStorage，返回列表时恢复
    saveFilter()
  } catch { /* handled by interceptor */ }
  finally { loading.value = false }
}

const saveFilter = () => {
  const data = {}
  if (keyword.value) data.keyword = keyword.value
  if (statusFilter.value) data.status = statusFilter.value
  if (deviceTypeFilter.value) data.device_type = deviceTypeFilter.value
  if (dateRange.value) {
    data.date_from = dayjs(dateRange.value[0]).format('YYYY-MM-DD')
    data.date_to = dayjs(dateRange.value[1]).format('YYYY-MM-DD')
  }
  if (page.value > 1) data.page = page.value
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => {
  keyword.value = ''
  statusFilter.value = ''
  deviceTypeFilter.value = ''
  dateRange.value = null
  page.value = 1
  sessionStorage.removeItem(STORAGE_KEY)
  fetchData()
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除该工单？', '删除确认', { type: 'warning' })
    await request.delete(`/work-orders/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch { /* cancelled */ }
}

onMounted(() => {
  // 从 sessionStorage 恢复筛选条件
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      const data = JSON.parse(raw)
      if (data.keyword) keyword.value = data.keyword
      if (data.status) statusFilter.value = data.status
      if (data.device_type) deviceTypeFilter.value = data.device_type
      if (data.date_from && data.date_to) {
        dateRange.value = [new Date(data.date_from), new Date(data.date_to)]
      }
      if (data.page) page.value = data.page
    } catch { /* ignore bad data */ }
  }
  // 拉取设备类型选项
  request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    .then(res => { deviceTypeOptions.value = flattenTree(res.items || []) })
    .catch(() => {})
  fetchData()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 260px; }
.filter-select { width: 150px; }
.action-btn { flex-shrink: 0; }
.secondary-btn { background: #fff; border-color: #d9d9d9; color: #333; }
.table-card { min-height: 300px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
.col-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.action-row { display: flex; gap: 6px; align-items: center; }
.progress-row { padding: 6px 8px; background: #F7F8FA; border-radius: 6px; width: 100%; justify-content: flex-end; }

.status-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.status-DRAFT { background: #F2F3F5; color: #4E5969; }
.status-IN_PROGRESS { background: #FFF3E8; color: #FF7D00; }
.status-ARCHIVING { background: #FFF7E8; color: #FF8800; }
.status-ARCHIVED { background: #E8F8EE; color: #00B42A; }
.status-COMPLETED { background: #E8F8EE; color: #00B42A; }
.filter-date { width: 240px; }
</style>
