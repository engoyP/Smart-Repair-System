<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">库存管理</h2>
      <div class="header-actions">
        <el-button @click="importDialog.visible = true">进货单导入</el-button>
        <el-button type="primary" @click="$router.push('/spare-parts/new')">新增备件</el-button>
      </div>
    </div>

    <!-- 库存预警横幅 -->
    <div v-if="alerts.alert_count > 0" class="alert-banner">
      <el-alert
        :title="`库存预警：${alerts.out_of_stock_count} 项缺货、${alerts.low_stock_count} 项低库存，共 ${alerts.alert_count} 项需关注`"
        type="warning"
        show-icon
        :closable="false"
      >
        <template #default>
          <el-button size="small" type="warning" plain @click="showAlerts = true; handleAlertFilter()">查看详情</el-button>
        </template>
      </el-alert>
    </div>

    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
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
    </el-card>

    <!-- 数据表格 -->
    <el-card class="table-card" shadow="never">
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
        <el-table-column prop="unit_price" label="单价" width="90" />
        <el-table-column prop="location" label="存放位置" width="110" />
        <el-table-column prop="supplier" label="供应商" width="110" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" type="primary" @click="$router.push(`/spare-parts/${row.id}`)">编辑</el-button>
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

    <!-- 库存预警详情弹窗 -->
    <el-dialog v-model="showAlerts" title="库存预警详情" width="700px">
      <template v-if="alerts.out_of_stock_items.length">
        <h4 style="color: #F53F3F; margin-bottom: 8px">缺货备件 ({{ alerts.out_of_stock_count }})</h4>
        <el-table :data="alerts.out_of_stock_items" size="small" style="margin-bottom: 16px">
          <el-table-column prop="part_code" label="编码" width="100" />
          <el-table-column prop="part_name" label="名称" min-width="140" />
          <el-table-column prop="stock_quantity" label="库存" width="60" />
          <el-table-column prop="safety_stock" label="安全库存" width="70" />
          <el-table-column prop="location" label="位置" width="100" />
        </el-table>
      </template>
      <template v-if="alerts.low_stock_items.length">
        <h4 style="color: #FF7D00; margin-bottom: 8px">低库存备件 ({{ alerts.low_stock_count }})</h4>
        <el-table :data="alerts.low_stock_items" size="small">
          <el-table-column prop="part_code" label="编码" width="100" />
          <el-table-column prop="part_name" label="名称" min-width="140" />
          <el-table-column prop="stock_quantity" label="库存" width="60" />
          <el-table-column prop="safety_stock" label="安全库存" width="70" />
          <el-table-column prop="location" label="位置" width="100" />
        </el-table>
      </template>
      <el-empty v-if="alerts.alert_count === 0" description="暂无库存预警" />
    </el-dialog>

    <!-- 进货单导入弹窗 -->
    <el-dialog v-model="importDialog.visible" title="进货单导入" width="700px" destroy-on-close>
      <el-alert
        title="批量导入备件进货数据，支持新增备件和更新已有备件库存"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <!-- 手动输入模式 -->
      <div style="margin-bottom: 12px">
        <el-button size="small" @click="addImportRow" :disabled="importDialog.items.length >= 50">
          添加一行
        </el-button>
        <el-button size="small" @click="clearImportRows" :disabled="importDialog.items.length === 0">
          清空
        </el-button>
        <span style="margin-left: 12px; color: #86909C; font-size: 13px">
          共 {{ importDialog.items.length }} 项
        </span>
      </div>

      <div style="max-height: 400px; overflow-y: auto">
        <el-table :data="importDialog.items" size="small" border>
          <el-table-column label="#" width="40">
            <template #default="{ $index }">{{ $index + 1 }}</template>
          </el-table-column>
          <el-table-column label="备件编码" width="120">
            <template #default="{ row }">
              <el-input v-model="row.part_code" size="small" placeholder="必填" />
            </template>
          </el-table-column>
          <el-table-column label="名称" width="130">
            <template #default="{ row }">
              <el-input v-model="row.part_name" size="small" placeholder="可选" />
            </template>
          </el-table-column>
          <el-table-column label="数量" width="80">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="1" size="small" style="width: 70px" />
            </template>
          </el-table-column>
          <el-table-column label="单价" width="80">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" :min="0" :precision="2" size="small" style="width: 70px" />
            </template>
          </el-table-column>
          <el-table-column label="供应商" width="110">
            <template #default="{ row }">
              <el-input v-model="row.supplier" size="small" placeholder="可选" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="60">
            <template #default="{ $index }">
              <el-button text type="danger" size="small" @click="importDialog.items.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="importDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importDialog.loading" :disabled="importDialog.items.length === 0">
          导入 ({{ importDialog.items.length }}项)
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入结果弹窗 -->
    <el-dialog v-model="importResult.visible" title="导入结果" width="480px">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="总条目">{{ importResult.data.total || 0 }}</el-descriptions-item>
        <el-descriptions-item label="新增备件">
          <span style="color: #00B42A; font-weight: 600">{{ importResult.data.created || 0 }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="更新库存">
          <span style="color: #3491FA; font-weight: 600">{{ importResult.data.updated || 0 }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="importResult.visible = false; fetchData(); fetchAlerts()">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const showAlerts = ref(false)

const alerts = reactive({
  alert_count: 0,
  low_stock_count: 0,
  out_of_stock_count: 0,
  low_stock_items: [],
  out_of_stock_items: [],
})

const importDialog = reactive({
  visible: false,
  loading: false,
  items: [],
})

const importResult = reactive({
  visible: false,
  data: {},
})

const stockLabel = (row) => {
  if (row.stock_quantity <= 0) return '缺件'
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
  } catch { /* handled */ }
  finally { loading.value = false }
}

const fetchAlerts = async () => {
  try {
    const res = await request.get('/spare-parts/alerts')
    Object.assign(alerts, res)
  } catch { /* handled */ }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; typeFilter.value = ''; stockFilter.value = ''; page.value = 1; fetchData() }
const handleAlertFilter = () => { stockFilter.value = 'out_of_stock'; page.value = 1; fetchData() }

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除该备件？', '删除确认', { type: 'warning' })
    await request.delete(`/spare-parts/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
    fetchAlerts()
  } catch { /* cancelled */ }
}

// 进货单导入
const addImportRow = () => {
  importDialog.items.push({
    part_code: '', part_name: '', quantity: 1, unit_price: 0,
    supplier: '', device_type: '', location: '',
  })
}
const clearImportRows = () => { importDialog.items = [] }

const handleImport = async () => {
  // 校验：编码必填
  const invalid = importDialog.items.some(item => !item.part_code.trim())
  if (invalid) {
    ElMessage.warning('请输入所有备件的编码')
    return
  }
  importDialog.loading = true
  try {
    const payload = { items: importDialog.items.map(item => ({
      part_code: item.part_code.trim(),
      part_name: item.part_name?.trim() || undefined,
      quantity: item.quantity,
      unit_price: item.unit_price,
      supplier: item.supplier?.trim() || undefined,
    }))}
    const res = await request.post('/spare-parts/import', payload)
    importResult.data = res
    importResult.visible = true
    importDialog.visible = false
    importDialog.items = []
  } catch { /* handled */ }
  finally { importDialog.loading = false }
}

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

onMounted(() => {
  fetchDeviceTypes()
  fetchData()
  fetchAlerts()
  // 预填一行进货单
  addImportRow()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.header-actions { display: flex; gap: 12px; }

.alert-banner { margin-bottom: 16px; }

.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.table-card { flex: 1; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }

.stock-status {
  display: inline-flex; align-items: center; gap: 4px; font-size: 13px;
}
.stock-status::before { content: ''; width: 6px; height: 6px; border-radius: 50%; }
.stock-ok::before { background: #00B42A; }
.stock-ok { color: #00B42A; }
.stock-low::before { background: #FF7D00; }
.stock-low { color: #FF7D00; }
.stock-out::before { background: #F53F3F; }
.stock-out { color: #F53F3F; }

.action-group { display: flex; gap: 8px; }
</style>
