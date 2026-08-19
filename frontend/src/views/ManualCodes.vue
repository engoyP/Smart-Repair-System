<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">设备手册错误码</h2>
        <span class="page-desc">从设备说明书导入的「错误码 → 故障诊断」权威映射（含出处），供 AI 问答检索引用</span>
      </div>
      <div class="header-actions">
        <el-button v-if="isAdmin" @click="openImportDialog">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>JSON 批量导入
        </el-button>
        <el-button v-if="isAdmin" type="primary" @click="openCreate">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>新增条目
        </el-button>
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
        <el-table-column label="等级" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.severity" :type="sevTagType(row.severity)" size="small">{{ sevLabel(row.severity) }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="170" show-overflow-tooltip />
        <el-table-column prop="device_type" label="设备类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.device_type" size="small" type="success" effect="plain">{{ row.device_type }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="manual_name" label="手册名称" min-width="170" show-overflow-tooltip />
        <el-table-column prop="chapter" label="章节" width="120" show-overflow-tooltip />
        <el-table-column prop="page" label="页码" width="70" />
        <el-table-column label="更新时间" width="140">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="showDetail(row)">查看</el-button>
            <el-button v-if="isAdmin" size="small" @click="openEdit(row)">编辑</el-button>
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
          <el-tag v-if="detailDialog.item.severity" :type="sevTagType(detailDialog.item.severity)" size="small">
            {{ sevLabel(detailDialog.item.severity) }}（{{ detailDialog.item.effect || '-' }}）
          </el-tag>
          <el-tag v-if="detailDialog.item.device_type" size="small" type="success" effect="plain">{{ detailDialog.item.device_type }}</el-tag>
        </div>
        <div class="detail-cite">
          <div class="cite-row"><span class="cite-label">手册</span>{{ detailDialog.item.manual_name }}</div>
          <div class="cite-row"><span class="cite-label">章节</span>{{ detailDialog.item.chapter }}</div>
          <div class="cite-row"><span class="cite-label">页码</span>{{ detailDialog.item.page }}</div>
          <div class="cite-row" v-if="detailDialog.item.related_codes?.length">
            <span class="cite-label">伴随报警</span>
            <el-tag v-for="rc in detailDialog.item.related_codes" :key="rc" size="small" effect="plain" style="margin-right:6px">{{ rc }}</el-tag>
          </div>
        </div>
        <div class="detail-block" v-if="detailDialog.item.message_text">
          <div class="detail-label">屏幕 / 日志原文</div>
          <div class="detail-content mono">{{ detailDialog.item.message_text }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-label">错误含义 / 触发条件</div>
          <div class="detail-content">{{ detailDialog.item.description }}</div>
        </div>
        <div class="detail-block" v-if="detailDialog.item.conditions?.length">
          <div class="detail-label">情形清单</div>
          <div v-for="(c, i) in detailDialog.item.conditions" :key="i" class="cond-card">
            <div class="cond-signal">情形{{ i + 1 }}：{{ c.signal }}</div>
            <div class="cond-line"><b>原因：</b>{{ c.cause }}</div>
            <div class="cond-line" v-if="c.steps"><b>处理：</b>{{ c.steps }}</div>
          </div>
        </div>
        <div class="detail-block" v-if="!detailDialog.item.conditions?.length && (detailDialog.item.causes || detailDialog.item.solutions)">
          <div class="detail-label">可能原因</div>
          <div class="detail-content">{{ detailDialog.item.causes || '未收录' }}</div>
          <div class="detail-label" style="margin-top: 12px">处理步骤 / 排查方向</div>
          <div class="detail-content">{{ detailDialog.item.solutions || '未收录' }}</div>
        </div>
      </template>
    </el-dialog>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="editDialog.visible" :title="editDialog.isEdit ? '编辑手册条目' : '新增手册条目'" width="760px" destroy-on-close>
      <div class="edit-toolbar">
        <el-button type="success" plain size="small" @click="aiDialog.visible = true">
          <el-icon style="margin-right: 4px"><MagicStick /></el-icon>AI 结构化（粘贴原文回填）
        </el-button>
        <span class="edit-tip">AI 结果仅预填，请人工核对后保存</span>
      </div>
      <el-form :model="editDialog.form" label-width="90px" label-position="left">
        <div class="form-grid">
          <el-form-item label="手册名称" required><el-input v-model="editDialog.form.manual_name" /></el-form-item>
          <el-form-item label="设备类型"><el-input v-model="editDialog.form.device_type" placeholder="如 数控机床 / 机器人" /></el-form-item>
          <el-form-item label="错误码" required><el-input v-model="editDialog.form.error_code" placeholder="如 SV0436" /></el-form-item>
          <el-form-item label="标题" required><el-input v-model="editDialog.form.title" /></el-form-item>
        </div>
        <el-form-item label="屏幕原文">
          <el-input v-model="editDialog.form.message_text" type="textarea" :rows="2" placeholder="设备屏幕/日志显示的原文，逐字照抄（检索锚点）" />
        </el-form-item>
        <el-form-item label="含义说明" required>
          <el-input v-model="editDialog.form.description" type="textarea" :rows="2" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="报警等级">
            <el-select v-model="editDialog.form.severity" clearable style="width: 100%">
              <el-option label="EX 急停" value="EX" /><el-option label="OH 停机" value="OH" /><el-option label="INFO 提示" value="INFO" />
            </el-select>
          </el-form-item>
          <el-form-item label="设备影响">
            <el-select v-model="editDialog.form.effect" clearable style="width: 100%">
              <el-option label="急停" value="急停" /><el-option label="停机" value="停机" /><el-option label="仅提示" value="仅提示" />
            </el-select>
          </el-form-item>
          <el-form-item label="章节"><el-input v-model="editDialog.form.chapter" /></el-form-item>
          <el-form-item label="页码"><el-input v-model="editDialog.form.page" /></el-form-item>
        </div>
        <el-form-item label="伴随报警">
          <el-select v-model="editDialog.form.related_codes" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入其它错误码后回车添加，如 SV0401">
            <el-option v-for="rc in knownCodes" :key="rc" :label="rc" :value="rc" />
          </el-select>
        </el-form-item>
        <el-form-item label="情形清单">
          <div class="cond-editor">
            <div v-for="(c, i) in editDialog.form.conditions" :key="i" class="cond-edit-card">
              <div class="cond-edit-head">
                <span class="cond-idx">情形 {{ i + 1 }}</span>
                <el-button size="small" type="danger" text @click="removeCondition(i)">删除</el-button>
              </div>
              <el-input v-model="c.signal" placeholder="日志可观察信号 / 触发条件（如：启动瞬间电流突增报警）" class="cond-edit-input" />
              <el-input v-model="c.cause" placeholder="原因" class="cond-edit-input" />
              <el-input v-model="c.steps" type="textarea" :rows="2" placeholder="处理/排查步骤" />
            </div>
            <el-button size="small" type="primary" plain @click="addCondition">
              <el-icon style="margin-right: 4px"><Plus /></el-icon>添加情形
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="editDialog.saving" @click="saveEntry">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 结构化弹窗 -->
    <el-dialog v-model="aiDialog.visible" title="AI 结构化：粘贴手册原文" width="640px" destroy-on-close>
      <el-input v-model="aiDialog.text" type="textarea" :rows="10" placeholder="粘贴设备手册「错误码表」章节原文（可含多个错误码，取第一条回填）" />
      <div class="ai-warn">DeepSeek 提取结构化字段，仅回填表单不落库，请人工核对后保存。</div>
      <template #footer>
        <el-button @click="aiDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="aiDialog.parsing" @click="runAiParse">开始结构化</el-button>
      </template>
    </el-dialog>

    <!-- JSON 批量导入弹窗 -->
    <el-dialog v-model="importDialog.visible" title="JSON 批量导入" width="520px" destroy-on-close>
      <el-upload
        drag
        action="#"
        :auto-upload="false"
        :on-change="onImportFileChange"
        :limit="1"
        accept=".json"
      >
        <div class="upload-hint">拖拽或点击选择 .json 文件<br/><span class="upload-sub">字段结构见 backend/scripts/manual_codes.example.json</span></div>
      </el-upload>
      <div v-if="importDialog.result" class="import-result">
        新建 {{ importDialog.result.created }} 条 · 更新 {{ importDialog.result.updated }} 条 · 失败 {{ importDialog.result.failed?.length || 0 }} 条
        <div v-for="f in importDialog.result.failed" :key="f.error_code" class="import-fail-line">✗ {{ f.error_code }}：{{ f.reason }}</div>
      </div>
      <template #footer>
        <el-button @click="importDialog.visible = false">关闭</el-button>
        <el-button type="primary" :loading="importDialog.importing" @click="runImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, MagicStick, Upload } from '@element-plus/icons-vue'
import request from '../api'
import dayjs from 'dayjs'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const deviceTypeFilter = ref('')
const deviceTypes = ref([])
const knownCodes = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const detailDialog = reactive({ visible: false, item: null })
const editDialog = reactive({ visible: false, isEdit: false, saving: false, editingId: null, form: emptyForm() })
const aiDialog = reactive({ visible: false, parsing: false, text: '' })
const importDialog = reactive({ visible: false, importing: false, file: null, result: null })

const currentUser = JSON.parse(localStorage.getItem('current_user') || '{}')
const isAdmin = computed(() => currentUser.role === 'ADMIN')

const sevTagType = (s) => ({ EX: 'danger', OH: 'warning', INFO: 'info' }[s] || 'info')
const sevLabel = (s) => ({ EX: 'EX 急停', OH: 'OH 停机', INFO: 'INFO 提示' }[s] || s)
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

function emptyForm() {
  return {
    manual_name: '', device_type: '', error_code: '', title: '',
    message_text: '', description: '', severity: '', effect: '',
    related_codes: [], conditions: [{ signal: '', cause: '', steps: '' }],
    chapter: '', page: '',
  }
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (deviceTypeFilter.value) params.device_type = deviceTypeFilter.value
    const res = await request.get('/manual-codes/', { params })
    list.value = res.items
    total.value = res.total
    knownCodes.value = [...new Set([...knownCodes.value, ...res.items.map(i => i.error_code).filter(Boolean)])]
  } catch { /* handled */ }
  finally { loading.value = false }
}

const loadDeviceTypes = async () => {
  try {
    const res = await request.get('/manual-codes/', { params: { page: 1, page_size: 100 } })
    deviceTypes.value = [...new Set(res.items.map(i => i.device_type).filter(Boolean))]
    knownCodes.value = [...new Set(res.items.map(i => i.error_code).filter(Boolean))]
  } catch { /* handled */ }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; deviceTypeFilter.value = ''; page.value = 1; fetchData() }

const showDetail = (row) => {
  detailDialog.item = row
  detailDialog.visible = true
}

const addCondition = () => editDialog.form.conditions.push({ signal: '', cause: '', steps: '' })
const removeCondition = (i) => editDialog.form.conditions.splice(i, 1)

const openCreate = () => {
  editDialog.form = emptyForm()
  editDialog.isEdit = false
  editDialog.editingId = null
  editDialog.visible = true
}

const openEdit = (row) => {
  editDialog.editingId = row.id
  editDialog.form = {
    manual_name: row.manual_name || '', device_type: row.device_type || '',
    error_code: row.error_code || '', title: row.title || '',
    message_text: row.message_text || '', description: row.description || '',
    severity: row.severity || '', effect: row.effect || '',
    related_codes: [...(row.related_codes || [])],
    conditions: (row.conditions || []).length ? JSON.parse(JSON.stringify(row.conditions)) : [{ signal: '', cause: '', steps: '' }],
    chapter: row.chapter || '', page: row.page || '',
  }
  editDialog.isEdit = true
  editDialog.visible = true
}

const saveEntry = async () => {
  const f = editDialog.form
  if (!f.manual_name || !f.error_code || !f.title || !f.description) {
    ElMessage.warning('请填写手册名称 / 错误码 / 标题 / 含义说明')
    return
  }
  f.conditions = f.conditions.filter(c => c.signal || c.cause || c.steps)
  editDialog.saving = true
  try {
    if (editDialog.isEdit) {
      await request.put(`/manual-codes/${editDialog.editingId}`, f)
      ElMessage.success('更新成功')
    } else {
      await request.post('/manual-codes/', f)
      ElMessage.success('创建成功')
    }
    editDialog.visible = false
    fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { editDialog.saving = false }
}

const runAiParse = async () => {
  if (!aiDialog.text.trim()) { ElMessage.warning('请粘贴手册原文'); return }
  aiDialog.parsing = true
  try {
    const res = await request.post('/manual-codes/parse', {
      manual_text: aiDialog.text,
      manual_name: editDialog.form.manual_name,
      device_type: editDialog.form.device_type,
    })
    const entries = res.entries || []
    if (!entries.length) { ElMessage.warning('未识别到错误码条目'); return }
    const e = entries[0]
    editDialog.form.error_code = e.error_code || editDialog.form.error_code
    editDialog.form.title = e.title || editDialog.form.title
    editDialog.form.message_text = e.message_text || ''
    editDialog.form.description = e.description || editDialog.form.description
    if (e.severity) editDialog.form.severity = e.severity
    if (e.effect) editDialog.form.effect = e.effect
    if (e.related_codes?.length) editDialog.form.related_codes = e.related_codes
    if (e.conditions?.length) editDialog.form.conditions = e.conditions
    if (e.chapter) editDialog.form.chapter = e.chapter
    if (e.page) editDialog.form.page = e.page
    aiDialog.visible = false
    ElMessage.success(`已回填 1 条（共识别 ${entries.length} 条），请人工核对后保存`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '结构化失败')
  } finally { aiDialog.parsing = false }
}

const openImportDialog = () => {
  importDialog.file = null
  importDialog.result = null
  importDialog.visible = true
}

const onImportFileChange = (uploadFile) => { importDialog.file = uploadFile.raw }

const runImport = async () => {
  if (!importDialog.file) { ElMessage.warning('请选择 JSON 文件'); return }
  importDialog.importing = true
  try {
    const text = await importDialog.file.text()
    let items
    try { items = JSON.parse(text) } catch { throw new Error('JSON 解析失败，请检查文件格式') }
    if (!Array.isArray(items) || !items.length) throw new Error('JSON 内容必须是数组')
    const res = await request.post('/manual-codes/import-json', { items })
    importDialog.result = res
    ElMessage.success(`导入完成：新建 ${res.created}，更新 ${res.updated}，失败 ${res.failed?.length || 0}`)
    fetchData()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '导入失败')
  } finally { importDialog.importing = false }
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
.detail-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.detail-cite {
  padding: 10px 14px;
  background: #FFF3E8;
  border: 1px solid #FFD8B5;
  border-radius: 8px;
  font-size: 13px;
  color: #B25000;
  margin-bottom: 16px;
}
.cite-row { display: flex; align-items: baseline; gap: 10px; line-height: 1.9; flex-wrap: wrap; }
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
.detail-content.mono { font-family: Consolas, Monaco, monospace; font-size: 13px; }

.cond-card {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--color-bg-page);
}
.cond-signal { font-weight: 600; font-size: 13px; color: #FF7D00; margin-bottom: 4px; }
.cond-line { font-size: 13px; line-height: 1.7; color: var(--color-text-primary); }

.edit-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.edit-tip { font-size: 12px; color: var(--color-text-tertiary); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.cond-editor { width: 100%; display: flex; flex-direction: column; gap: 10px; }
.cond-edit-card {
  border: 1px dashed var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--color-bg-page);
}
.cond-edit-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.cond-idx { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); }
.cond-edit-input { margin-bottom: 8px; }

.ai-warn { margin-top: 10px; font-size: 12px; color: #B25000; }
.upload-hint { color: var(--color-text-secondary); font-size: 13px; line-height: 1.8; }
.upload-sub { color: var(--color-text-tertiary); font-size: 12px; }
.import-result { margin-top: 14px; font-size: 13px; color: var(--color-text-primary); }
.import-fail-line { color: #F56C6C; font-size: 12px; margin-top: 4px; }
</style>
