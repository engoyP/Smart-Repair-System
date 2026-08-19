<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">{{ isNew ? '新增设备' : '编辑设备' }}</h2>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基础信息" name="basic">
          <el-form :model="form" label-width="120px" style="max-width: 800px">
            <el-form-item label="设备编码" required>
              <el-input v-model="form.device_code" placeholder="如 EQ-001" />
            </el-form-item>
            <el-form-item label="设备名称" required>
              <el-input v-model="form.device_name" placeholder="如 主电机" />
            </el-form-item>
            <el-form-item label="外部系统关联ID">
              <el-input v-model="form.ext_system_id" placeholder="对接外部监控系统时绑定的唯一ID" />
            </el-form-item>
            <el-form-item label="设备类型">
              <el-select v-model="form.device_type" clearable filterable placeholder="选择设备类型" style="width: 100%">
                <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="型号">
              <el-input v-model="form.model" placeholder="如 Y2-280S-4" />
            </el-form-item>
            <el-form-item label="制造商">
              <el-input v-model="form.manufacturer" placeholder="如 西门子" />
            </el-form-item>
            <el-form-item label="位置">
              <el-input v-model="form.location" placeholder="如 A车间-1号生产线" />
            </el-form-item>
            <el-form-item label="采购日期">
              <el-date-picker v-model="form.purchase_date" type="date" placeholder="选择日期" style="width: 100%" />
            </el-form-item>
            <el-form-item label="保修到期">
              <el-date-picker v-model="form.warranty_expiry" type="date" placeholder="选择日期" style="width: 100%" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注信息" />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="监控参数" name="monitor">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="tip"
            title="手动修改用于调试/初始化；接入外部监控系统后，以下字段将通过 API 自动同步，建议不要手动修改。"
          />
          <el-form :model="form" label-width="120px" style="max-width: 800px; margin-top:16px;">
            <el-form-item label="运行状态">
              <el-select v-model="form.run_status" placeholder="选择状态" style="width: 100%">
                <el-option label="正常 ONLINE" value="ONLINE" />
                <el-option label="离线 OFFLINE" value="OFFLINE" />
                <el-option label="告警 ALARM" value="ALARM" />
                <el-option label="故障 FAULT" value="FAULT" />
                <el-option label="未知 UNKNOWN" value="UNKNOWN" />
              </el-select>
            </el-form-item>
            <el-form-item label="最后心跳">
              <el-date-picker v-model="form.last_heartbeat" type="datetime" placeholder="选择心跳时间" style="width: 100%" />
            </el-form-item>
            <el-form-item label="状态来源">
              <el-select v-model="form.status_source" clearable placeholder="选择来源" style="width: 100%">
                <el-option label="手动 manual" value="manual" />
                <el-option label="外部系统 external" value="external" />
                <el-option label="自动推断 auto" value="auto" />
              </el-select>
            </el-form-item>
            <el-form-item label="状态原因">
              <el-input v-model="form.status_reason" type="textarea" :rows="2" placeholder="证据链说明，如『30分钟未心跳』『外部系统上报CRITICAL故障』" />
            </el-form-item>
            <el-form-item label="最后同步时间">
              <el-date-picker v-model="form.last_sync_time" type="datetime" placeholder="选择同步时间" style="width: 100%" />
            </el-form-item>
            <el-form-item label="故障标签">
              <div class="fault-editor">
                <div class="fault-list">
                  <div
                    v-for="(t, i) in faultList"
                    :key="i"
                    class="fault-item"
                  >
                    <el-select v-model="t.level" size="small" style="width: 100px">
                      <el-option label="INFO" value="INFO" />
                      <el-option label="WARNING" value="WARNING" />
                      <el-option label="ERROR" value="ERROR" />
                      <el-option label="CRITICAL" value="CRITICAL" />
                    </el-select>
                    <el-input v-model="t.code" size="small" placeholder="编码" style="width: 120px" />
                    <el-input v-model="t.name" size="small" placeholder="名称" style="width: 160px" />
                    <el-input v-model="t.message" size="small" placeholder="描述" style="flex:1" />
                    <el-button size="small" type="danger" link @click="faultList.splice(i, 1)">删除</el-button>
                  </div>
                </div>
                <el-button size="small" type="primary" plain @click="addFault" style="margin-top:8px">+ 添加故障标签</el-button>
              </div>
            </el-form-item>
            <el-form-item label="扩展字段(JSON)">
              <el-input
                v-model="monitorExtraRaw"
                type="textarea"
                :rows="4"
                placeholder='{ "cpu_usage": 78, "ambient_temp": 32 }'
              />
              <div class="sub-tip" v-if="monitorExtraInvalid">JSON 格式错误，将不会保存</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <div style="margin-top: 16px;">
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
        <el-button @click="$router.back()">返回</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../api'

const route = useRoute()
const router = useRouter()
const isNew = computed(() => !route.params.id || route.params.id === 'new')
const saving = ref(false)
const activeTab = ref('basic')

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}
const deviceTypeOptions = ref([])

const form = ref({
  device_code: '',
  device_name: '',
  device_type: '',
  model: '',
  manufacturer: '',
  location: '',
  purchase_date: null,
  warranty_expiry: null,
  remark: '',
  run_status: 'UNKNOWN',
  last_heartbeat: null,
  fault_tags: [],
  ext_system_id: '',
  status_source: null,
  status_reason: '',
  last_sync_time: null,
  monitor_extra: null,
})

const faultList = ref([])
watch(
  () => form.value.fault_tags,
  (val) => {
    faultList.value = val?.map?.(t => ({ ...t })) || []
  },
  { immediate: true }
)
const addFault = () => faultList.value.push({ level: 'WARNING', code: '', name: '', message: '', triggered_at: new Date().toISOString() })

const monitorExtraRaw = ref('')
const monitorExtraInvalid = ref(false)
watch(
  () => form.value.monitor_extra,
  (val) => {
    monitorExtraRaw.value = val != null ? JSON.stringify(val, null, 2) : ''
  },
  { immediate: true }
)
watch(monitorExtraRaw, (val) => {
  if (!val || !val.trim()) { monitorExtraInvalid.value = false; return }
  try { JSON.parse(val); monitorExtraInvalid.value = false } catch { monitorExtraInvalid.value = true }
})

const loadData = async () => {
  if (isNew.value) return
  const res = await request.get(`/devices/${route.params.id}`)
  Object.assign(form.value, res)
  if (res.purchase_date) form.value.purchase_date = new Date(res.purchase_date)
  if (res.warranty_expiry) form.value.warranty_expiry = new Date(res.warranty_expiry)
  if (res.last_heartbeat) form.value.last_heartbeat = new Date(res.last_heartbeat)
  if (res.last_sync_time) form.value.last_sync_time = new Date(res.last_sync_time)
  faultList.value = (res.fault_tags || []).map(t => ({ ...t }))
  monitorExtraRaw.value = res.monitor_extra != null ? JSON.stringify(res.monitor_extra, null, 2) : ''
}

const handleSave = async () => {
  saving.value = true
  try {
    const data = { ...form.value }
    if (data.purchase_date instanceof Date) data.purchase_date = data.purchase_date.toISOString().split('T')[0]
    if (data.warranty_expiry instanceof Date) data.warranty_expiry = data.warranty_expiry.toISOString().split('T')[0]
    // 故障标签：过滤空 code/name
    data.fault_tags = faultList.value.filter(t => t.code && t.name)
    // 扩展字段
    if (monitorExtraRaw.value && monitorExtraRaw.value.trim()) {
      try { data.monitor_extra = JSON.parse(monitorExtraRaw.value) } catch { data.monitor_extra = form.value.monitor_extra }
    } else {
      data.monitor_extra = null
    }
    if (isNew.value) {
      await request.post('/devices/', data)
      ElMessage.success('创建成功')
    } else {
      await request.put(`/devices/${route.params.id}`, data)
      ElMessage.success('更新成功')
    }
    router.push('/devices')
  } finally { saving.value = false }
}

onMounted(async () => {
  try {
    const res = await request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    deviceTypeOptions.value = flattenTree(res.items || [])
  } catch { /* ignore */ }
  if (!isNew.value) loadData()
})
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.tip { margin-bottom: 8px; }
.fault-editor { width: 100%; }
.fault-list { display: flex; flex-direction: column; gap: 6px; }
.fault-item { display: flex; gap: 6px; align-items: center; }
.sub-tip { color: #DC2626; font-size: 12px; margin-top: 4px; }
</style>
