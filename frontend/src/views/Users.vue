<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">用户管理</h2>
      <el-button type="primary" @click="dialogVisible = true">添加用户</el-button>
    </div>

    <el-card class="table-card" shadow="never">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column label="用户" width="180">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 8px;">
              <el-avatar :size="32" icon="UserFilled" />
              <span>{{ row.real_name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <span class="role-tag" :class="'role-' + row.role">{{ roleLabel(row.role) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" width="200" />
        <el-table-column prop="phone" label="手机" width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="status-dot" :class="row.is_active ? 'active' : 'inactive'">
              {{ row.is_active ? '启用' : '禁用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="钉钉" width="100">
          <template #default="{ row }">
            <span v-if="row.dingtalk_userid" class="dt-bound-tag">已绑定</span>
            <span v-else class="dt-unbound-tag">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" type="primary" @click="handleEdit(row)">编辑</el-button>
              <el-button size="small" type="warning" @click="handleResetPwd(row)">重置密码</el-button>
              <el-button v-if="!row.dingtalk_userid" size="small" type="success" plain @click="openBindDingTalk(row)">绑定钉钉</el-button>
              <el-button v-else size="small" type="info" @click="handleUnbindDingTalk(row)">解绑钉钉</el-button>
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

    <!-- 新增/编辑弹窗 -->
    <el-dialog :title="editingId ? '编辑用户' : '添加用户'" v-model="dialogVisible" width="500px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item v-if="!editingId" label="密码" required>
          <el-input v-model="form.password" type="password" placeholder="初始密码" show-password />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="邮箱地址" />
        </el-form-item>
        <el-form-item label="手机">
          <el-input v-model="form.phone" placeholder="手机号" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="管理员" value="ADMIN" />
            <el-option label="技术员" value="TECHNICIAN" />
            <el-option label="主管" value="SUPERVISOR" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 钉钉扫码绑定弹窗（管理员代绑） -->
    <el-dialog
      v-model="bindDialogVisible"
      :title="`绑定钉钉 - ${bindTarget ? bindTarget.real_name : ''}`"
      width="360px"
      :close-on-click-modal="false"
      @closed="cleanupBindScan({ full: true })"
    >
      <div class="dt-scan-area">
        <div class="dt-qr-box" :class="{ expired: dtBindStatus === 'expired' }">
          <qrcode-vue
            v-if="dtBindUrl && dtBindStatus !== 'expired'"
            :value="dtBindUrl"
            :size="220"
            level="M"
          />
          <div v-else-if="dtBindLoading" class="dt-qr-loading">加载二维码中...</div>
          <div v-else-if="dtBindStatus === 'expired'" class="dt-qr-expired" @click="initBindScan">
            <span>二维码已过期</span>
            <span style="color:#165DFF">点击刷新</span>
          </div>
          <!-- 扫码成功蒙层 -->
          <div v-if="dtBindStatus === 'scanned'" class="dt-qr-scanned">
            <div class="dt-qr-scanned-text">
              <div>扫码成功</div>
              <div>{{ dtBindUser?.name || '' }}</div>
            </div>
          </div>
        </div>
        <div v-if="dtBindStatus === 'pending'" class="dt-qr-countdown">
          二维码 {{ dtBindCountdown }} 秒后过期
        </div>
        <div class="dt-scan-tip">请使用手机钉钉扫描二维码，授权后绑定到该用户</div>
        <div class="dt-scan-actions">
          <el-button type="primary" size="large" :disabled="dtBindStatus !== 'scanned'" :loading="dtBindConfirming" @click="confirmBindDingTalk">
            {{ dtBindStatus === 'scanned' ? '确认绑定' : '等待扫码...' }}
          </el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import QrcodeVue from 'qrcode.vue'
import request from '../api'
import dayjs from 'dayjs'

const list = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)

const form = ref({
  username: '', password: '', real_name: '', email: '', phone: '',
  role: 'TECHNICIAN', is_active: true
})

const roleMap = { ADMIN: '管理员', TECHNICIAN: '技术员', SUPERVISOR: '主管' }
const roleLabel = (r) => roleMap[r] || r
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const fetchData = async () => {
  loading.value = true
  try {
    const res = await request.get('/users/', { params: { page: page.value, page_size: pageSize.value } })
    list.value = res.items
    total.value = res.total
  } catch { /* handled */ }
  finally { loading.value = false }
}

const resetForm = () => {
  editingId.value = null
  form.value = { username: '', password: '', real_name: '', email: '', phone: '', role: 'TECHNICIAN', is_active: true }
}

const handleEdit = (row) => {
  editingId.value = row.id
  form.value = { ...row, password: '' }
  dialogVisible.value = true
}

const handleResetPwd = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt('请输入新密码', '重置密码', { inputType: 'password' })
    if (value) {
      await request.put(`/users/${row.id}`, { password: value })
      ElMessage.success('密码重置成功')
    }
  } catch { /* cancelled */ }
}

const handleSave = async () => {
  saving.value = true
  try {
    const data = { ...form.value }
    if (editingId.value && !data.password) delete data.password
    if (editingId.value) {
      await request.put(`/users/${editingId.value}`, data)
      ElMessage.success('更新成功')
    } else {
      await request.post('/users/', data)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchData()
  } finally { saving.value = false }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除该用户？', '删除确认', { type: 'warning' })
    await request.delete(`/users/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch { /* cancelled */ }
}

const handleUnbindDingTalk = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定解绑用户「${row.real_name}」的钉钉账号？解绑后该用户将无法通过钉钉扫码登录。`,
      '解绑确认',
      { type: 'warning' }
    )
    await request.post(`/users/${row.id}/dingtalk/unbind`)
    ElMessage.success('钉钉账号已解绑')
    fetchData()
  } catch { /* cancelled */ }
}

// ===== 管理员扫码代绑钉钉（真实扫码流程） =====
const bindDialogVisible = ref(false)
const bindTarget = ref(null)
const dtBindUrl = ref('')
const dtBindState = ref('')
const dtBindStatus = ref('pending')  // pending | scanned | expired
const dtBindUser = ref(null)
const dtBindLoading = ref(false)
const dtBindConfirming = ref(false)
const dtBindCountdown = ref(120)
let dtBindPollTimer = null
let dtBindRefreshTimer = null

const cleanupBindScan = (opts = {}) => {
  // 默认只清轮询定时器；传 full=true 才连倒计时一起清
  const { full = false } = opts
  if (dtBindPollTimer) { clearInterval(dtBindPollTimer); dtBindPollTimer = null }
  if (full && dtBindRefreshTimer) { clearInterval(dtBindRefreshTimer); dtBindRefreshTimer = null }
  if (full) {
    dtBindStatus.value = 'pending'
    dtBindUser.value = null
  }
}

const openBindDingTalk = (row) => {
  bindTarget.value = row
  bindDialogVisible.value = true
  initBindScan()
}

const initBindScan = () => {
  // 先完整清理
  cleanupBindScan({ full: true })
  dtBindLoading.value = true
  dtBindStatus.value = 'pending'
  dtBindUser.value = null
  dtBindUrl.value = ''
  dtBindCountdown.value = 120

  // ===== 修复 1：倒计时 Timer 移到外层 =====
  dtBindRefreshTimer = setInterval(() => {
    if (dtBindStatus.value !== 'pending') return
    dtBindCountdown.value--
    if (dtBindCountdown.value <= 0) {
      // ===== 修复 2：倒计时到 0 不自动刷新 =====
      if (dtBindRefreshTimer) { clearInterval(dtBindRefreshTimer); dtBindRefreshTimer = null }
      if (dtBindPollTimer) { clearInterval(dtBindPollTimer); dtBindPollTimer = null }
      dtBindStatus.value = 'expired'
    }
  }, 1000)

  // bind_user_id=目标用户ID：扫码成功后绑定到该用户（需主管/管理员权限）
  request.post('/auth/dingtalk/scan/generate', {}, { params: { bind_user_id: bindTarget.value.id } })
    .then(res => {
      dtBindUrl.value = res.url
      dtBindState.value = res.state
      dtBindPollTimer = setInterval(() => pollBindStatus(), 2000)
      if (res.expire_seconds && Math.abs(res.expire_seconds - 120) > 10) {
        dtBindCountdown.value = res.expire_seconds
      }
    })
    .catch(e => {
      ElMessage.error(e?.response?.data?.detail || '生成钉钉二维码失败')
      if (dtBindRefreshTimer) { clearInterval(dtBindRefreshTimer); dtBindRefreshTimer = null }
    })
    .finally(() => { dtBindLoading.value = false })
}

const pollBindStatus = async () => {
  if (!dtBindState.value) return
  try {
    const res = await request.get(`/auth/dingtalk/scan/status/${dtBindState.value}`)
    if (res.status === 'scanned') {
      dtBindStatus.value = 'scanned'
      dtBindUser.value = res.user_info
      // ===== 修复 3：只清轮询定时器 =====
      cleanupBindScan({ full: false })
    } else if (res.status === 'expired') {
      dtBindStatus.value = 'expired'
      cleanupBindScan({ full: true })
    } else if (res.expires_in != null && dtBindStatus.value === 'pending') {
      if (Math.abs(res.expires_in - dtBindCountdown.value) > 5) {
        dtBindCountdown.value = res.expires_in
      }
    }
  } catch { /* 静默忽略轮询错误 */ }
}

const confirmBindDingTalk = async () => {
  if (dtBindStatus.value !== 'scanned') return
  dtBindConfirming.value = true
  try {
    const res = await request.post(`/auth/dingtalk/scan/confirm/${dtBindState.value}`)
    if (res.status === 'bound') {
      ElMessage.success(`已为「${res.real_name || bindTarget.value?.real_name}」绑定钉钉账号`)
      bindDialogVisible.value = false
      fetchData()
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '绑定失败')
    cleanupBindScan({ full: true })
  } finally {
    dtBindConfirming.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.table-card { flex: 1; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }

.role-tag {
  display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; line-height: 20px;
}
.role-ADMIN { background: #FFECEC; color: #F53F3F; }
.role-SUPERVISOR { background: #FFF3E8; color: #FF7D00; }
.role-TECHNICIAN { background: #E8F9F9; color: #0FC6C2; }

.status-dot { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; }
.status-dot::before { content: ''; width: 6px; height: 6px; border-radius: 50%; }
.status-dot.active { color: #00B42A; }
.status-dot.active::before { background: #00B42A; }
.status-dot.inactive { color: #C9CDD4; }
.status-dot.inactive::before { background: #C9CDD4; }
.dt-bound-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  color: #0089FF;
  background: #E8F3FF;
}
.dt-unbound-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  color: #86909C;
  background: #F2F3F5;
}

/* 钉钉扫码绑定弹窗 */
.dt-scan-area {
  padding: 8px 0;
}
.dt-qr-box {
  width: 220px;
  height: 220px;
  margin: 0 auto 16px;
  padding: 14px;
  background: #fff;
  border: 2px solid #E5E6EB;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: border-color .2s;
}
.dt-qr-box.expired {
  border-color: #C9CDD4;
}
.dt-qr-box svg, .dt-qr-box canvas {
  max-width: 100%;
  max-height: 100%;
}
.dt-qr-loading, .dt-qr-expired {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #86909C;
  font-size: 13px;
  text-align: center;
}
.dt-qr-expired { cursor: pointer; }
.dt-qr-scanned {
  position: absolute;
  inset: 0;
  background: rgba(255,255,255,0.95);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.dt-qr-scanned-text {
  text-align: center;
}
.dt-qr-scanned-text > div:first-child {
  font-size: 16px;
  font-weight: 600;
  color: #1D2129;
}
.dt-qr-countdown {
  font-size: 12px;
  color: #0FC6C2;
  text-align: center;
  margin-bottom: 8px;
}
.dt-scan-tip {
  font-size: 13px;
  color: #4E5969;
  text-align: center;
  margin-bottom: 16px;
}
.dt-scan-actions {
  margin-bottom: 8px;
  text-align: center;
}
</style>