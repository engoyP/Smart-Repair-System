<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">设备监控</h2>
      <div class="header-actions">
        <el-tag v-if="autoRefresh" type="success" effect="light" round>实时刷新中 (15s)</el-tag>
        <el-button @click="handleToggleRefresh" :type="autoRefresh ? 'warning' : 'success'">
          {{ autoRefresh ? '停止刷新' : '开启实时刷新' }}
        </el-button>
        <el-button @click="fetchAll">手动刷新</el-button>
        <el-button v-if="!isPureSupervisor" type="primary" @click="$router.push('/devices/new')">新增设备</el-button>
      </div>
    </div>

    <!-- 监控统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="8" :md="4" v-for="s in statCards" :key="s.key">
        <el-card shadow="never" class="stat-card" :class="`stat-${s.key}`" @click="handleStatClick(s)">
          <div class="stat-icon" :style="{ background: s.bg, color: s.color }">{{ s.icon }}</div>
          <div class="stat-content">
            <div class="stat-label">{{ s.label }}</div>
            <div class="stat-value" :style="{ color: s.color }">{{ stats[s.key] ?? 0 }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索设备编码/名称" clearable class="filter-input"
          @clear="handleSearch" @keyup.enter="handleSearch" />
        <el-select v-model="typeFilter" placeholder="设备类型" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="运行状态" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="hasFaultFilter" placeholder="故障标签" clearable class="filter-select" @change="handleSearch">
          <el-option label="有故障" :value="true" />
          <el-option label="无故障" :value="false" />
        </el-select>
        <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
        <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
      </div>
    </el-card>

    <!-- 设备监控列表 -->
    <el-card class="table-card" shadow="never">
      <el-table :data="list" v-loading="loading" stripe row-class-name="mon-row">
        <el-table-column label="设备" min-width="260">
          <template #default="{ row }">
            <div class="device-cell">
              <div class="device-name-row">
                <el-tag size="small" :type="statusMeta[row.run_status]?.type ?? 'info'" effect="dark" round class="status-tag">
                  {{ statusMeta[row.run_status]?.label ?? '未知' }}
                </el-tag>
                <span class="device-name">{{ row.device_name }}</span>
              </div>
              <div class="device-meta">
                <span class="code">{{ row.device_code }}</span>
                <span class="sep">·</span>
                <span>{{ row.device_type || '-' }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="型号" width="140" />
        <el-table-column prop="manufacturer" label="制造商" width="140" />
        <el-table-column prop="location" label="位置" width="160" />
        <el-table-column label="故障标签" min-width="240">
          <template #default="{ row }">
            <div v-if="row.fault_tags && row.fault_tags.length > 0" class="fault-tags">
              <el-tag
                v-for="t in row.fault_tags"
                :key="t.code"
                size="small"
                :type="faultTagType(t.level)"
                effect="light"
                class="fault-tag"
              >
                <template #title>
                  {{ t.message || t.name }}
                  <span v-if="t.triggered_at"> · 触发 {{ formatTime(t.triggered_at) }}</span>
                </template>
                {{ t.name }}
              </el-tag>
            </div>
            <span v-else class="dim">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态原因" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="status-reason">{{ row.status_reason || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isPureSupervisor" label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" type="primary" @click="$router.push(`/devices/${row.id}`)">编辑</el-button>
              <el-button
                v-if="row.fault_tags && row.fault_tags.length"
                size="small" type="success" @click="handleClearFaults(row)"
              >清故障</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
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
import { ref, onMounted, onBeforeUnmount, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'
import dayjs from 'dayjs'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const statusFilter = ref('')
const hasFaultFilter = ref(null)
const deviceTypeOptions = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const autoRefresh = ref(false)
const stats = reactive({
  total: 0, online: 0, offline: 0, alarm: 0, fault: 0, unknown: 0,
  with_fault_tags: 0,
})

// 当前登录用户权限
const currentUser = (() => {
  try {
    const raw = localStorage.getItem('current_user')
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
})()
const isPureSupervisor = currentUser.role === 'SUPERVISOR'

const statusOptions = [
  { label: '正常', value: 'ONLINE' },
  { label: '离线', value: 'OFFLINE' },
  { label: '告警', value: 'ALARM' },
  { label: '故障', value: 'FAULT' },
  { label: '未知', value: 'UNKNOWN' },
]

const statusMeta = {
  ONLINE:  { label: '正常',  type: 'success', color: '#10B981' },
  OFFLINE: { label: '离线',  type: 'info',    color: '#6B7280' },
  ALARM:   { label: '告警',  type: 'warning', color: '#F59E0B' },
  FAULT:   { label: '故障',  type: 'danger',  color: '#EF4444' },
  UNKNOWN: { label: '未知',  type: 'info',    color: '#9CA3AF' },
}

const statCards = [
  { key: 'total',   label: '设备总数', icon: '▣', bg: '#EFF6FF', color: '#2563EB' },
  { key: 'online',  label: '正常运行', icon: '✓', bg: '#ECFDF5', color: '#059669' },
  { key: 'offline', label: '离线设备', icon: '⊘', bg: '#F3F4F6', color: '#6B7280' },
  { key: 'alarm',   label: '告警设备', icon: '!', bg: '#FFFBEB', color: '#D97706' },
  { key: 'fault',   label: '故障设备', icon: '✕', bg: '#FEF2F2', color: '#DC2626' },
  { key: 'unknown', label: '状态未知', icon: '?', bg: '#F9FAFB', color: '#9CA3AF' },
]

const faultTagType = (lvl) => {
  const m = { CRITICAL: 'danger', ERROR: 'danger', WARNING: 'warning', INFO: 'info' }
  return m[(lvl || 'WARNING').toUpperCase()] || 'warning'
}

const formatDate = (d) => d ? dayjs(d).format('YYYY-MM-DD') : '-'
const formatTime = (t) => t ? dayjs(t).format('MM-DD HH:mm') : '-'

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}

const fetchDeviceTypes = async () => {
  try {
    const res = await request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    deviceTypeOptions.value = flattenTree(res.items || [])
  } catch { /* empty */ }
}

const fetchStats = async () => {
  try {
    const res = await request.get('/devices/monitor/stats', { params: typeFilter.value ? { device_type: typeFilter.value } : {} })
    Object.assign(stats, res)
  } catch { /* ignore */ }
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (typeFilter.value) params.device_type = typeFilter.value
    if (statusFilter.value) params.run_status = statusFilter.value
    if (hasFaultFilter.value != null) params.has_fault = hasFaultFilter.value
    const res = await request.get('/devices/', { params })
    list.value = res.items
    total.value = res.total
  } catch { /* ignore */ }
  finally { loading.value = false }
}

const fetchAll = () => { fetchStats(); fetchData() }

const handleSearch = () => { page.value = 1; fetchAll() }
const handleReset = () => {
  keyword.value = ''; typeFilter.value = ''; statusFilter.value = ''; hasFaultFilter.value = null
  page.value = 1
  fetchAll()
}

const handleStatClick = (s) => {
  if (s.key === 'total' || s.key === 'unknown') {
    statusFilter.value = s.key === 'total' ? '' : 'UNKNOWN'
  } else if (s.key === 'with_fault_tags') {
    hasFaultFilter.value = true; statusFilter.value = ''
  } else {
    statusFilter.value = s.value?.toUpperCase() || s.key.toUpperCase()
  }
  hasFaultFilter.value = s.key === 'with_fault_tags' ? true : hasFaultFilter.value
  page.value = 1
  fetchData()
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除设备「${row.device_name}」？`, '删除确认', { type: 'warning' })
    await request.delete(`/devices/${row.id}`)
    ElMessage.success('删除成功')
    fetchAll()
  } catch { /* cancelled */ }
}

const handleClearFaults = async (row) => {
  try {
    await ElMessageBox.confirm(`清理「${row.device_name}」的故障标签？状态将重置为未知。`, '清理确认', { type: 'warning' })
    await request.post(`/devices/monitor/${row.id}/clear-faults`)
    ElMessage.success('已清理故障标签')
    fetchAll()
  } catch { /* cancelled */ }
}

const handleToggleRefresh = () => { autoRefresh.value = !autoRefresh.value }

let timer = null
onMounted(async () => {
  await fetchDeviceTypes()
  fetchAll()
  timer = setInterval(() => { if (autoRefresh.value) fetchAll() }, 15000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.header-actions { display: flex; gap: 10px; align-items: center; }
.stats-row { margin-bottom: 16px; }
.stat-card { cursor: pointer; transition: all 0.2s; }
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.stat-card :deep(.el-card__body) { display: flex; align-items: center; gap: 12px; padding: 14px 16px; }
.stat-icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; flex-shrink: 0; }
.stat-content { flex: 1; }
.stat-label { font-size: 12px; color: #6B7280; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 700; line-height: 1.2; }

.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 220px; }
.filter-select { width: 140px; }
.action-btn { flex-shrink: 0; }
.table-card { flex: 1; }
.action-group { display: flex; gap: 6px; flex-wrap: wrap; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }

.device-cell { display: flex; flex-direction: column; gap: 4px; }
.device-name-row { display: flex; align-items: center; gap: 8px; }
.status-tag { font-size: 12px; padding: 0 8px; height: 22px; line-height: 20px; }
.device-name { font-weight: 600; color: var(--color-text-primary); font-size: 14px; }
.device-meta { color: #6B7280; font-size: 12px; display: flex; align-items: center; gap: 6px; }
.device-meta .code { font-family: ui-monospace, monospace; }
.device-meta .sep { color: #D1D5DB; }

.fault-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.fault-tag { font-size: 12px; }

.dim { color: #9CA3AF; }
.small { font-size: 11px; }
.status-reason { color: #6B7280; font-size: 12px; }
:deep(.mon-row) { height: 60px; }
</style>
