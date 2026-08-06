<template>
  <div class="fault-codes-page">
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">故障码映射管理</h2>
        <p class="page-desc">故障码与故障描述一一对应，由系统自动生成，不可修改或删除</p>
      </div>
      <el-button type="warning" @click="openCreateDialog">+ 新增故障码</el-button>
    </div>

    <!-- 搜索区 -->
    <div class="search-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索故障码或故障描述..."
        :prefix-icon="Search"
        clearable
        class="search-input"
        @keydown.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select v-model="deviceFilter" clearable placeholder="全部设备类型" class="device-select" @change="handleSearch">
        <el-option v-for="d in allDeviceTypes" :key="d" :label="d" :value="d" />
      </el-select>
      <el-button type="primary" :icon="Search" @click="handleSearch">搜索</el-button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-number">{{ total }}</div>
        <div class="stat-label">故障码总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ allDeviceTypes.length }}</div>
        <div class="stat-label">涉及设备类型</div>
      </div>
    </div>

    <!-- 表格 -->
    <el-table :data="items" stripe v-loading="loading" class="fault-table">
      <el-table-column prop="fault_code" label="故障码" width="200">
        <template #default="{ row }">
          <el-tag type="warning" size="large">{{ row.fault_code }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="fault_description" label="故障描述" min-width="400" show-overflow-tooltip />
      <el-table-column prop="device_type" label="设备类型" width="150">
        <template #default="{ row }">
          <span v-if="row.device_type">
            <el-tag type="info" size="small">{{ row.device_type }}</el-tag>
          </span>
          <span v-if="!row.device_type">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="收录时间" width="180">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="showDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-bar" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadData"
      />
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="dialogVisible" title="故障码详情" width="500px">
      <template v-if="currentItem">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="故障码">
            <el-tag type="warning" size="large">{{ currentItem.fault_code }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="故障描述">{{ currentItem.fault_description }}</el-descriptions-item>
          <el-descriptions-item label="设备类型">{{ currentItem.device_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="收录时间">{{ formatTime(currentItem.created_at) }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新增故障码弹窗 -->
    <el-dialog v-model="createDialog.visible" title="新增故障码" width="500px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="设备类型">
          <el-select v-model="createDialog.deviceType" clearable filterable placeholder="选择设备类型（可选）" style="width:100%">
            <el-option v-for="d in allDeviceTypes" :key="d" :label="d" :value="d" />
          </el-select>
          <div class="cascader-hint">系统根据设备类型自动分配编码前缀，不选则默认为 99 前缀</div>
        </el-form-item>
        <el-form-item label="故障描述" required>
          <el-input
            v-model="createDialog.description"
            type="textarea"
            :rows="4"
            placeholder="请填写故障描述，如：注塑机料筒温度偏高报警"
          />
        </el-form-item>
      </el-form>

      <!-- 结果提示 -->
      <div v-if="createDialog.result" class="fc-dialog-result">
        <div v-if="createDialog.result.is_new">
          <el-alert
            title="新增成功"
            type="success"
            show-icon
            :closable="false"
          >
            <template #default>故障码 {{ createDialog.result.fault_code }} 已自动生成并收录</template>
          </el-alert>
        </div>
        <div v-if="!createDialog.result.is_new">
          <el-alert
            title="检测到重复"
            type="warning"
            show-icon
            :closable="false"
          >
            <template #default>{{ createDialog.result.duplicate_hint }}</template>
          </el-alert>
        </div>
      </div>

      <div class="fc-dialog-footer">
        <el-button @click="closeCreateDialog">取消</el-button>
        <div v-if="!createDialog.result" style="display:inline">
          <el-button type="primary" :loading="createDialog.creating" @click="handleCreateFaultCode">
            {{ createDialog.creating ? '生成中...' : '自动生成故障码' }}
          </el-button>
        </div>
        <div v-if="createDialog.result" style="display:inline">
          <el-button type="primary" @click="closeCreateDialog">关闭</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../api'
import dayjs from 'dayjs'

const keyword = ref('')
const deviceFilter = ref('')
const items = ref([])
const allDeviceTypes = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const dialogVisible = ref(false)
const currentItem = ref(null)

const createDialog = reactive({
  visible: false,
  deviceType: '',
  description: '',
  creating: false,
  result: null,
})

const loadDeviceTypes = async () => {
  try {
    const res = await request.get('/fault-codes/device-types')
    allDeviceTypes.value = res.device_types || []
  } catch { /* ignore */ }
}

const loadData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (deviceFilter.value) params.device_type = deviceFilter.value

    const res = await request.get('/fault-codes/', { params })
    items.value = res.items || []
    total.value = res.total || 0
  } catch { /* ignore */ }
  finally { loading.value = false }
}

const handleSearch = () => {
  page.value = 1
  loadData()
}

const showDetail = (row) => {
  currentItem.value = row
  dialogVisible.value = true
}

const formatTime = (t) => {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

// ==================== 新增故障码 ====================

const openCreateDialog = () => {
  createDialog.deviceType = deviceFilter.value || ''
  createDialog.description = ''
  createDialog.result = null
  createDialog.visible = true
}

const closeCreateDialog = () => {
  createDialog.visible = false
  createDialog.result = null
  loadData()
  loadDeviceTypes()
}

const handleCreateFaultCode = async () => {
  if (!createDialog.description.trim()) {
    ElMessage.warning('请填写故障描述')
    return
  }
  createDialog.creating = true
  try {
    const res = await request.post('/fault-codes/create', {
      fault_description: createDialog.description.trim(),
      device_type: createDialog.deviceType || undefined,
    })
    createDialog.result = res
    if (res.is_new) {
      ElMessage.success(`新故障码 ${res.fault_code} 已自动生成`)
    } else {
      ElMessage.info(res.duplicate_hint)
    }
  } catch (e) {
    ElMessage.error('新增故障码失败')
  } finally {
    createDialog.creating = false
  }
}

onMounted(() => {
  loadData()
  loadDeviceTypes()
})
</script>

<style scoped>
.fault-codes-page { padding: 0 4px; }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.page-header-left { }

.page-title {
  font-size: 20px;
  font-weight: 700;
  color: #1D2129;
  margin: 0 0 4px 0;
}
.page-desc { font-size: 13px; color: #86909C; margin: 0; }

.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}
.search-input { width: 360px; }
.device-select { width: 180px; }

.stats-row { display: flex; gap: 16px; margin-bottom: 20px; }
.stat-card {
  background: #F7F8FA;
  border-radius: 8px;
  padding: 16px 24px;
  min-width: 140px;
}
.stat-number {
  font-size: 26px;
  font-weight: 700;
  color: #0FC6C2;
  line-height: 1.2;
}
.stat-label { font-size: 12px; color: #86909C; margin-top: 2px; }

.fault-table { width: 100%; }

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.fc-dialog-result { margin-top: 16px; }
.cascader-hint { font-size: 12px; color: #86909C; margin-top: 4px; line-height: 1.4; }
.fc-dialog-footer { display: flex; gap: 8px; justify-content: flex-end; }
</style>
