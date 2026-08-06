<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">仓库库存</h2>
      <div class="header-actions">
        <el-button type="warning" :loading="pushing" @click="handlePushToLogistics">
          推送库存预警至后勤
        </el-button>
        <el-button @click="showPushHistory = true">推送记录</el-button>
      </div>
    </div>

    <!-- 概览卡片 -->
    <div class="overview-cards">
      <div class="overview-card">
        <div class="card-label">备件总数</div>
        <div class="card-value">{{ overview.total }}</div>
        <div class="card-sub">项</div>
      </div>
      <div class="overview-card card-warning">
        <div class="card-label">低库存预警</div>
        <div class="card-value">{{ overview.lowStock }}</div>
        <div class="card-sub">项需关注</div>
      </div>
      <div class="overview-card card-danger">
        <div class="card-label">缺货预警</div>
        <div class="card-value">{{ overview.outOfStock }}</div>
        <div class="card-sub">项急需补充</div>
      </div>
    </div>

    <!-- 库存预警列表 -->
    <div v-if="alerts.alert_count > 0" class="alert-section">
      <div class="section-header">
        <h3 class="section-title">
          <el-icon style="color: #FF7D00"><WarningFilled /></el-icon>
          库存预警清单（{{ alerts.alert_count }} 项）
        </h3>
        <el-button size="small" type="warning" plain @click="handlePushToLogistics" :loading="pushing">
          一键推送至后勤
        </el-button>
      </div>

      <!-- 缺货 -->
      <div v-if="alerts.out_of_stock_items.length" class="alert-group">
        <h4 class="alert-group-title out-of-stock-title">缺货备件</h4>
        <el-table :data="alerts.out_of_stock_items" size="small" border>
          <el-table-column prop="part_code" label="编码" width="120" />
          <el-table-column prop="part_name" label="名称" min-width="150" show-overflow-tooltip />
          <el-table-column prop="specification" label="规格" width="120" />
          <el-table-column prop="device_type" label="适用设备" width="100" />
          <el-table-column label="库存" width="70">
            <template #default="{ row }">
              <span class="stock-out-text">{{ row.stock_quantity }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="safety_stock" label="安全库存" width="80" />
          <el-table-column prop="supplier" label="供应商" width="110" show-overflow-tooltip />
          <el-table-column label="紧急程度" width="100">
            <template #default>
              <el-tag type="danger" size="small">紧急</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 低库存 -->
      <div v-if="alerts.low_stock_items.length" class="alert-group">
        <h4 class="alert-group-title low-stock-title">低库存备件</h4>
        <el-table :data="alerts.low_stock_items" size="small" border>
          <el-table-column prop="part_code" label="编码" width="120" />
          <el-table-column prop="part_name" label="名称" min-width="150" show-overflow-tooltip />
          <el-table-column prop="specification" label="规格" width="120" />
          <el-table-column prop="device_type" label="适用设备" width="100" />
          <el-table-column label="库存" width="70">
            <template #default="{ row }">
              <span class="stock-low-text">{{ row.stock_quantity }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="safety_stock" label="安全库存" width="80" />
          <el-table-column prop="supplier" label="供应商" width="110" show-overflow-tooltip />
          <el-table-column label="紧急程度" width="100">
            <template #default>
              <el-tag type="warning" size="small">关注</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div v-else class="alert-section">
      <el-empty description="所有备件库存充足，暂无预警" :image-size="80" />
    </div>

    <!-- 库存明细列表 -->
    <el-card class="table-card" shadow="never">
      <div class="section-header">
        <h3 class="section-title">库存明细</h3>
      </div>

      <div class="filter-bar" style="margin-bottom: 16px">
        <el-input v-model="keyword" placeholder="搜索编码/名称/规格" clearable class="filter-input" @clear="handleSearch" @keyup.enter="handleSearch" />
        <el-select v-model="typeFilter" placeholder="设备类型" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
        <el-select v-model="stockFilter" placeholder="库存状态" clearable class="filter-select" @change="handleSearch">
          <el-option label="库存不足" value="low_stock" />
          <el-option label="已缺货" value="out_of_stock" />
        </el-select>
        <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
        <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
      </div>

      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column prop="part_code" label="备件编码" width="120" />
        <el-table-column prop="part_name" label="备件名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="specification" label="规格型号" width="140" />
        <el-table-column prop="unit" label="单位" width="60" />
        <el-table-column prop="stock_quantity" label="库存" width="70" sortable />
        <el-table-column prop="safety_stock" label="安全库存" width="80" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <span class="stock-status" :class="stockClass(row)">{{ stockLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="device_type" label="适用设备" width="100" />
        <el-table-column prop="location" label="存放位置" width="110" />
        <el-table-column prop="supplier" label="供应商" width="110" show-overflow-tooltip />
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

    <!-- 推送结果弹窗 -->
    <el-dialog v-model="pushResult.visible" title="推送结果" width="480px">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="低库存预警">{{ pushResult.data.low_stock_count || 0 }} 项</el-descriptions-item>
        <el-descriptions-item label="缺货预警">{{ pushResult.data.out_of_stock_count || 0 }} 项</el-descriptions-item>
        <el-descriptions-item label="已推送预警数">
          <span :style="{ color: pushResult.data.alert_count > 0 ? '#FF7D00' : '#00B42A', fontWeight: 600 }">
            {{ pushResult.data.alert_count || 0 }} 项
          </span>
        </el-descriptions-item>
      </el-descriptions>
      <div v-if="pushResult.data.alert_count > 0" style="margin-top: 12px; color: #4E5969; font-size: 13px">
        预警信息已推送至钉钉通知，后勤系统将及时收到补货提醒。
      </div>
      <div v-else style="margin-top: 12px; color: #00B42A; font-size: 13px">
        当前库存状况良好，无需推送预警。
      </div>
      <template #footer>
        <el-button type="primary" @click="pushResult.visible = false; fetchAlerts()">确定</el-button>
      </template>
    </el-dialog>

    <!-- 推送记录弹窗 -->
    <el-dialog v-model="showPushHistory" title="推送记录" width="600px">
      <el-timeline>
        <el-timeline-item
          v-for="(item, idx) in pushHistory"
          :key="idx"
          :timestamp="item.time"
          :type="item.alertCount > 0 ? 'warning' : 'success'"
          placement="top"
        >
          <p>
            {{ item.alertCount > 0 ? `推送 ${item.alertCount} 项库存预警至后勤系统` : '库存检查完成，无预警' }}
          </p>
          <p v-if="item.alertCount > 0" style="color: #86909C; font-size: 12px">
            低库存 {{ item.lowStock }} 项 / 缺货 {{ item.outOfStock }} 项
          </p>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="pushHistory.length === 0" description="暂无推送记录" :image-size="60" />
      <template #footer>
        <el-button @click="showPushHistory = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref('')
const deviceTypeOptions = ref([])
const stockFilter = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const pushing = ref(false)
const showPushHistory = ref(false)

const overview = reactive({
  total: 0,
  lowStock: 0,
  outOfStock: 0,
})

const alerts = reactive({
  alert_count: 0,
  low_stock_count: 0,
  out_of_stock_count: 0,
  low_stock_items: [],
  out_of_stock_items: [],
})

const pushResult = reactive({
  visible: false,
  data: {},
})

const pushHistory = ref([])

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
  } catch { /* fallback to empty */ }
}

const stockLabel = (row) => {
  if (row.stock_quantity <= 0) return '缺货'
  if (row.stock_quantity <= row.safety_stock) return '紧张'
  return '充足'
}
const stockClass = (row) => {
  if (row.stock_quantity <= 0) return 'stock-out'
  if (row.stock_quantity <= row.safety_stock) return 'stock-low'
  return 'stock-ok'
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (typeFilter.value) params.device_type = typeFilter.value
    if (stockFilter.value) params.stock_status = stockFilter.value
    const res = await request.get('/spare-parts/', { params })
    list.value = res.items
    total.value = res.total
    overview.total = res.total
  } catch { /* handled */ }
  finally { loading.value = false }
}

const fetchAlerts = async () => {
  try {
    const res = await request.get('/spare-parts/alerts')
    Object.assign(alerts, res)
    overview.lowStock = res.low_stock_count
    overview.outOfStock = res.out_of_stock_count
  } catch { /* handled */ }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; typeFilter.value = ''; stockFilter.value = ''; page.value = 1; fetchData() }

const handlePushToLogistics = async () => {
  pushing.value = true
  try {
    const res = await request.post('/spare-parts/check-alerts')
    pushResult.data = res
    pushResult.visible = true
    // 记录推送历史
    pushHistory.value.unshift({
      time: new Date().toLocaleString('zh-CN'),
      alertCount: res.alert_count || 0,
      lowStock: res.low_stock_count || 0,
      outOfStock: res.out_of_stock_count || 0,
    })
    if (res.alert_count > 0) {
      ElMessage.success(`已推送 ${res.alert_count} 项库存预警至后勤系统`)
    } else {
      ElMessage.success('库存检查完成，当前无预警')
    }
  } catch {
    ElMessage.error('推送失败，请稍后重试')
  } finally {
    pushing.value = false
  }
}

onMounted(() => {
  fetchDeviceTypes()
  fetchData()
  fetchAlerts()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-actions {
  display: flex;
  gap: 12px;
}

/* 概览卡片 */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.overview-card {
  background: #FFFFFF;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 20px;
  box-shadow: var(--shadow-card);
  transition: box-shadow .2s;
}
.overview-card:hover {
  box-shadow: var(--shadow-card-hover);
}
.card-label {
  font-size: 13px;
  color: var(--color-text-tertiary);
  margin-bottom: 8px;
}
.card-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.2;
}
.card-sub {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-top: 4px;
}
.card-warning .card-value { color: #FF7D00; }
.card-danger .card-value { color: #F53F3F; }

/* 预警区域 */
.alert-section {
  margin-bottom: 16px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.alert-group {
  margin-bottom: 16px;
}
.alert-group-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-left: 12px;
  border-left: 3px solid;
}
.out-of-stock-title {
  color: #F53F3F;
  border-color: #F53F3F;
}
.low-stock-title {
  color: #FF7D00;
  border-color: #FF7D00;
}

/* 表格卡片 */
.table-card {
  flex: 1;
}

/* 库存状态 */
.stock-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}
.stock-status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.stock-ok::before { background: #00B42A; }
.stock-ok { color: #00B42A; }
.stock-low::before { background: #FF7D00; }
.stock-low { color: #FF7D00; }
.stock-out::before { background: #F53F3F; }
.stock-out { color: #F53F3F; }

.stock-out-text { color: #F53F3F; font-weight: 600; }
.stock-low-text { color: #FF7D00; font-weight: 600; }

@media (max-width: 1200px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 768px) {
  .overview-cards {
    grid-template-columns: 1fr;
  }
}
</style>