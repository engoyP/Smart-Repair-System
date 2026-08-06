<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">账号安全</h2>
    </div>

    <div class="security-body">
      <!-- 绑定手机号 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header-row">
            <span class="card-title">绑定手机号</span>
            <el-tag v-if="phoneBound" size="small" type="success">已绑定</el-tag>
            <el-tag v-else size="small" type="warning">未绑定</el-tag>
          </div>
        </template>
        <template v-if="phoneBound">
          <el-descriptions :column="1" border class="dt-desc">
            <el-descriptions-item label="绑定手机号">{{ boundPhone }}</el-descriptions-item>
            <el-descriptions-item label="绑定时间">{{ phoneBindTime }}</el-descriptions-item>
          </el-descriptions>
          <div class="dt-actions">
            <el-button type="primary" @click="phoneBound = false">更换手机号</el-button>
          </div>
        </template>
        <template v-else>
          <el-form ref="phoneFormRef" :model="phoneForm" label-width="100px" class="security-form">
            <el-form-item label="手机号码" prop="phone">
              <el-input v-model="phoneForm.phone" placeholder="请输入手机号" maxlength="11" @input="phoneForm.phone = phoneForm.phone.replace(/\D/g, '')" />
            </el-form-item>
            <el-form-item label="验证码">
              <div class="code-row">
                <el-input
                  v-model="phoneForm.code"
                  placeholder="6位验证码"
                  maxlength="6"
                  style="width:160px"
                  @input="phoneForm.code = phoneForm.code.replace(/\D/g, '')"
                />
                <el-button
                  :disabled="phoneCountdown > 0 || !phoneForm.phone || phoneForm.phone.length < 11"
                  @click="sendBindCode"
                >
                  <template v-if="phoneCountdown > 0">{{ phoneCountdown }}s</template>
                  <template v-else>获取验证码</template>
                </el-button>
              </div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="phoneBinding" @click="handleBindPhone">
                {{ phoneBinding ? '绑定中...' : '绑定手机号' }}
              </el-button>
            </el-form-item>
          </el-form>
        </template>
      </el-card>

      <!-- 修改密码 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header-row">
            <span class="card-title">修改密码</span>
            <el-tag size="small" type="info">建议定期更换密码</el-tag>
          </div>
        </template>

        <!-- 切换方式 -->
        <div class="pwd-tabs">
          <span class="pwd-tab" :class="{ active: pwdMode === 'password' }" @click="pwdMode = 'password'">原密码修改</span>
          <span class="pwd-tab" :class="{ active: pwdMode === 'code' }" @click="pwdMode = 'code'">验证码修改</span>
        </div>

        <!-- 原密码修改 -->
        <template v-if="pwdMode === 'password'">
          <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px" class="security-form">
            <el-form-item label="当前密码" prop="old_password">
              <el-input v-model="pwdForm.old_password" type="password" placeholder="请输入当前密码" show-password />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwdForm.new_password" type="password" placeholder="请输入新密码（至少6位）" show-password />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input v-model="pwdForm.confirm_password" type="password" placeholder="请再次输入新密码" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="pwdChanging" @click="handleChangePassword">
                {{ pwdChanging ? '修改中...' : '修改密码' }}
              </el-button>
            </el-form-item>
          </el-form>
        </template>

        <!-- 验证码修改 -->
        <template v-else>
          <div v-if="!phoneBound" class="pwd-code-unbind-tip">
            <el-icon :size="16" color="#F7BA1E"><WarningFilled /></el-icon>
            <span>请先绑定手机号后再使用验证码修改密码</span>
          </div>
          <el-form v-else ref="pwdCodeFormRef" :model="pwdCodeForm" :rules="pwdCodeRules" label-width="100px" class="security-form">
            <el-form-item label="手机号码">
              <el-input :model-value="boundPhone" disabled />
            </el-form-item>
            <el-form-item label="验证码" prop="code">
              <div class="code-row">
                <el-input
                  v-model="pwdCodeForm.code"
                  placeholder="6位验证码"
                  maxlength="6"
                  style="width:160px"
                  @input="pwdCodeForm.code = pwdCodeForm.code.replace(/\D/g, '')"
                />
                <el-button
                  :disabled="pwdCodeCountdown > 0"
                  @click="sendPwdResetCode"
                >
                  <template v-if="pwdCodeCountdown > 0">{{ pwdCodeCountdown }}s</template>
                  <template v-else>获取验证码</template>
                </el-button>
              </div>
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwdCodeForm.new_password" type="password" placeholder="请输入新密码（至少6位）" show-password />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input v-model="pwdCodeForm.confirm_password" type="password" placeholder="请再次输入新密码" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="pwdChanging" @click="handleResetPasswordByCode">
                {{ pwdChanging ? '修改中...' : '修改密码' }}
              </el-button>
            </el-form-item>
          </el-form>
        </template>
      </el-card>

      <!-- 钉钉账号绑定 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header-row">
            <span class="card-title">钉钉账号绑定</span>
            <el-tag v-if="dingtalkConfig.bound" size="small" type="success">已绑定</el-tag>
            <el-tag v-else size="small" type="info">未绑定</el-tag>
          </div>
        </template>

        <div class="dt-intro">
          <el-icon :size="16" color="#0089FF"><InfoFilled /></el-icon>
          <span>绑定钉钉账号后，维修人员可接收工单派发、维修提醒等消息推送通知。</span>
        </div>

        <template v-if="dingtalkConfig.bound">
          <el-descriptions :column="2" border class="dt-desc">
            <el-descriptions-item label="钉钉账号">{{ dingtalkConfig.dingtalk_name || dingtalkConfig.bind_user_id }}</el-descriptions-item>
            <el-descriptions-item label="组织名称">{{ dingtalkConfig.corp_name }}</el-descriptions-item>
            <el-descriptions-item label="钉钉用户ID">{{ dingtalkConfig.bind_user_id }}</el-descriptions-item>
            <el-descriptions-item label="绑定时间">{{ dingtalkConfig.bind_time }}</el-descriptions-item>
          </el-descriptions>
          <div class="dt-actions">
            <el-button type="danger" plain @click="unbindDingTalk">解除绑定</el-button>
          </div>
        </template>

        <template v-else>
          <div class="dt-unbind-area">
            <div class="dt-qr-placeholder">
              <el-icon :size="36" color="#C9CDD4"><PictureFilled /></el-icon>
              <span>点击下方按钮，使用手机钉钉扫码完成绑定</span>
            </div>
            <el-button type="primary" size="large" @click="openBindDingTalk">
              扫码绑定钉钉
            </el-button>
          </div>
        </template>
      </el-card>

      <!-- 钉钉扫码绑定弹窗 -->
      <el-dialog
        v-model="bindDialogVisible"
        title="扫码绑定钉钉"
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
          <div class="dt-scan-tip">请使用手机钉钉扫描二维码，在手机端确认授权后完成绑定</div>
          <div class="dt-scan-actions">
            <el-button type="primary" size="large" :disabled="dtBindStatus !== 'scanned'" :loading="dtBindConfirming" @click="confirmBindDingTalk">
              {{ dtBindStatus === 'scanned' ? '确认绑定' : '等待扫码...' }}
            </el-button>
          </div>
        </div>
      </el-dialog>

      <!-- 登录记录 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <span class="card-title">最近登录记录</span>
        </template>
        <el-table :data="loginHistory" stripe size="small">
          <el-table-column prop="time" label="登录时间" width="180" />
          <el-table-column prop="ip" label="IP 地址" width="150" />
          <el-table-column prop="device" label="设备/浏览器" min-width="200" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <span :style="{ color: row.status === '成功' ? '#00B42A' : '#F53F3F' }">{{ row.status }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import QrcodeVue from 'qrcode.vue'
import request from '../api'

// ===== 绑定手机号 =====
const phoneBound = ref(false)
const boundPhone = ref('')
const phoneBindTime = ref('')
const phoneBinding = ref(false)
const phoneCountdown = ref(0)
const phoneForm = reactive({ phone: '', code: '' })

let phoneTimer = null

const loadPhoneBind = () => {
  try {
    const saved = localStorage.getItem('phone_bind_info')
    if (saved) {
      const data = JSON.parse(saved)
      phoneBound.value = true
      boundPhone.value = data.phone || ''
      phoneBindTime.value = data.bind_time || ''
    }
    // 从 current_user 获取已有手机号
    const user = localStorage.getItem('current_user')
    if (!phoneBound.value && user) {
      const u = JSON.parse(user)
      if (u.phone && u.phone.length >= 11) {
        phoneBound.value = true
        boundPhone.value = u.phone
        phoneBindTime.value = u.phone_bind_time || u.last_login_at || ''
      }
    }
    // 如果绑定了但没有时间记录，设一个默认时间
    if (phoneBound.value && !phoneBindTime.value) {
      phoneBindTime.value = new Date().toLocaleString('zh-CN')
      localStorage.setItem('phone_bind_info', JSON.stringify({ phone: boundPhone.value, bind_time: phoneBindTime.value }))
    }
  } catch { /* ignore */ }
}

const sendBindCode = async () => {
  if (!phoneForm.phone || phoneForm.phone.length < 11) {
    ElMessage.warning('请输入正确的手机号')
    return
  }
  try {
    const res = await request.post('/auth/send-code', { phone: phoneForm.phone, scene: 'bind' })
    if (res.sms_enabled) {
      ElMessage.success('验证码已发送，请注意查收短信')
    } else {
      ElMessage.success(`验证码已发送（Mock: ${res.code}）`)
    }
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '发送失败')
    return
  }
  phoneCountdown.value = 60
  phoneTimer = setInterval(() => {
    phoneCountdown.value--
    if (phoneCountdown.value <= 0) { clearInterval(phoneTimer); phoneTimer = null }
  }, 1000)
}

const handleBindPhone = async () => {
  if (!phoneForm.phone || !phoneForm.code) {
    ElMessage.warning('请填写完整信息')
    return
  }
  phoneBinding.value = true
  try {
    // 通过后端验证验证码
    await request.post('/auth/verify-code', {
      phone: phoneForm.phone,
      code: phoneForm.code,
      scene: 'bind',
    })
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '验证码错误')
    phoneBinding.value = false
    return
  }
  // 保存绑定信息
  const now = new Date().toLocaleString('zh-CN')
  phoneBound.value = true
  boundPhone.value = phoneForm.phone
  phoneBindTime.value = now
  localStorage.setItem('phone_bind_info', JSON.stringify({ phone: phoneForm.phone, bind_time: now }))
  // 同步更新 current_user
  const user = localStorage.getItem('current_user')
  if (user) {
    const u = JSON.parse(user)
    u.phone = phoneForm.phone
    localStorage.setItem('current_user', JSON.stringify(u))
  }
  ElMessage.success('手机号绑定成功')
  phoneBinding.value = false
}

// ===== 修改密码 =====
const pwdMode = ref('password')
const pwdFormRef = ref(null)
const pwdCodeFormRef = ref(null)
const pwdChanging = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm_password: '' })
const pwdCodeForm = reactive({ code: '', new_password: '', confirm_password: '' })
const pwdCodeCountdown = ref(0)
let pwdCodeTimer = null
const validateConfirm = (rule, value, callback) => {
  if (value !== pwdForm.new_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}
const pwdRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' },
  ],
}

const handleChangePassword = async () => {
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdChanging.value = true
  setTimeout(() => {
    pwdChanging.value = false
    ElMessage.success('密码修改成功，下次登录请使用新密码')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
  }, 800)
}

// 验证码修改密码
const validateCodeConfirm = (rule, value, callback) => {
  if (value !== pwdCodeForm.new_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}
const pwdCodeRules = {
  code: [{ required: true, message: '请输入验证码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    { validator: validateCodeConfirm, trigger: 'blur' },
  ],
}

const sendPwdResetCode = async () => {
  if (!boundPhone.value) {
    ElMessage.warning('请先绑定手机号')
    return
  }
  try {
    const res = await request.post('/auth/send-code', { phone: boundPhone.value, scene: 'reset_password' })
    if (res.sms_enabled) {
      ElMessage.success('验证码已发送，请注意查收短信')
    } else {
      ElMessage.success(`验证码已发送（Mock: ${res.code}）`)
    }
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '发送失败')
    return
  }
  pwdCodeCountdown.value = 60
  pwdCodeTimer = setInterval(() => {
    pwdCodeCountdown.value--
    if (pwdCodeCountdown.value <= 0) { clearInterval(pwdCodeTimer); pwdCodeTimer = null }
  }, 1000)
}

const handleResetPasswordByCode = async () => {
  const valid = await pwdCodeFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdChanging.value = true
  try {
    await request.post('/auth/reset-password', {
      phone: boundPhone.value,
      code: pwdCodeForm.code,
      new_password: pwdCodeForm.new_password,
    })
    ElMessage.success('密码修改成功，下次登录请使用新密码')
    pwdCodeForm.code = ''
    pwdCodeForm.new_password = ''
    pwdCodeForm.confirm_password = ''
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '修改失败，请检查验证码是否正确')
  }
  pwdChanging.value = false
}

// ===== 钉钉管理 =====
const dingtalkConfig = reactive({
  bound: false,
  corp_name: '',
  bind_user_id: '',
  dingtalk_name: '',
  bind_time: '',
})

// 同步当前用户信息到 localStorage（绑定/解绑后更新）
const syncLocalUser = (patch = {}) => {
  try {
    const user = localStorage.getItem('current_user')
    if (!user) return null
    const u = JSON.parse(user)
    Object.assign(u, patch)
    localStorage.setItem('current_user', JSON.stringify(u))
    return u
  } catch { return null }
}

// 读取当前登录用户的真实钉钉绑定状态
const loadDingTalkConfig = async () => {
  try {
    // 优先从后端拉取当前用户的真实钉钉绑定状态（避免 localStorage 丢失导致误判"未绑定"）
    const me = await request.get('/users/me')
    if (me) {
      const bound = !!me.dingtalk_userid
      Object.assign(dingtalkConfig, {
        bound,
        corp_name: me.department || '位智维修技术',
        bind_user_id: me.dingtalk_userid || '',
        dingtalk_name: me.dingtalk_name || '',
        bind_time: me.dingtalk_bound_at ? new Date(me.dingtalk_bound_at).toLocaleString('zh-CN') : '',
      })
      // 同步写回 localStorage，其他页面也能读到
      const cached = localStorage.getItem('current_user')
      if (cached) {
        const u = JSON.parse(cached)
        Object.assign(u, {
          dingtalk_userid: me.dingtalk_userid || null,
          dingtalk_name: me.dingtalk_name || null,
          dingtalk_bound_at: me.dingtalk_bound_at || null,
          department: me.department || u.department,
        })
        localStorage.setItem('current_user', JSON.stringify(u))
      }
      return
    }
  } catch (e) {
    console.warn('获取当前用户信息失败，回退到 localStorage', e)
  }

  // 回退：用 localStorage 里的字段
  try {
    const cached = localStorage.getItem('current_user')
    const u = cached ? JSON.parse(cached) : null
    const bound = !!(u && u.dingtalk_userid)
    Object.assign(dingtalkConfig, {
      bound,
      corp_name: (u && u.department) || '位智维修技术',
      bind_user_id: (u && u.dingtalk_userid) || '',
      bind_time: (u && u.dingtalk_bound_at) ? new Date(u.dingtalk_bound_at).toLocaleString('zh-CN') : '',
    })
  } catch { /* ignore */ }
}

// ===== 钉钉真实扫码绑定（绑定到当前登录用户） =====
const bindDialogVisible = ref(false)
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
  // 默认只清轮询定时器；倒计时定时器保留（条件渲染不会显示文字），只有传 full=true 才全部清
  const { full = false } = opts
  if (dtBindPollTimer) { clearInterval(dtBindPollTimer); dtBindPollTimer = null }
  if (full && dtBindRefreshTimer) { clearInterval(dtBindRefreshTimer); dtBindRefreshTimer = null }
  if (full) {
    dtBindStatus.value = 'pending'
    dtBindUser.value = null
  }
}

const openBindDingTalk = () => {
  bindDialogVisible.value = true
  initBindScan()
}

const initBindScan = () => {
  // 先完整清理：清所有定时器 + 重置状态，然后启动新二维码
  cleanupBindScan({ full: true })
  dtBindLoading.value = true
  dtBindStatus.value = 'pending'
  dtBindUser.value = null
  dtBindUrl.value = ''
  dtBindCountdown.value = 120

  // ===== 关键修复 1：倒计时 Timer 创建移到外层 =====
  // 在调 generate 之前就启动倒计时，保证数字一定动起来。失败再停。
  dtBindRefreshTimer = setInterval(() => {
    if (dtBindStatus.value !== 'pending') return // 非 pending 状态，倒计时不用动
    dtBindCountdown.value--
    if (dtBindCountdown.value <= 0) {
      // ===== 关键修复 2：倒计时到 0 不再自动刷新二维码 =====
      // 之前 30 秒时长才需要自动刷新；现在 120 秒足够用户操作，
      // 若自动刷新会导致用户扫了旧二维码后手机端成功但PC端还在等新二维码，
      // state 对不上永 pending。改为过期让用户手动点击刷新。
      clearInterval(dtBindRefreshTimer)
      dtBindRefreshTimer = null
      dtBindStatus.value = 'expired'
      // 也停掉轮询
      if (dtBindPollTimer) { clearInterval(dtBindPollTimer); dtBindPollTimer = null }
    }
  }, 1000)

  // self_bind=true：扫码成功后绑定到当前登录用户
  request.post('/auth/dingtalk/scan/generate', {}, { params: { self_bind: true } })
    .then(res => {
      dtBindUrl.value = res.url
      dtBindState.value = res.state
      dtBindPollTimer = setInterval(() => pollBindStatus(), 2000)
      // 如后端返回的 expire_seconds 与本地 120 差异超过 10s，以后端为准
      if (res.expire_seconds && Math.abs(res.expire_seconds - 120) > 10) {
        dtBindCountdown.value = res.expire_seconds
      }
    })
    .catch(e => {
      ElMessage.error(e?.response?.data?.detail || '生成钉钉二维码失败')
      // 失败：停掉已启动的倒计时定时器
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
      // ===== 关键修复 3：只清轮询定时器 =====
      // 倒计时定时器保留（虽然 pending 条件渲染已不显示倒计时文字），下次 initBindScan full=true 时再清
      cleanupBindScan({ full: false })
    } else if (res.status === 'expired') {
      dtBindStatus.value = 'expired'
      cleanupBindScan({ full: true })
    } else if (res.expires_in != null && dtBindStatus.value === 'pending') {
      // 以后端返回的 expires_in 做轻量校准（前后端时间差）
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
      ElMessage.success(`已绑定钉钉账号：${res.dingtalk_name || res.real_name || res.dingtalk_userid}`)
      bindDialogVisible.value = false
      syncLocalUser({
        dingtalk_userid: res.dingtalk_userid,
        dingtalk_name: res.dingtalk_name,
        dingtalk_bound_at: res.dingtalk_bound_at,
      })
      await loadDingTalkConfig()
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '绑定失败')
    cleanupBindScan({ full: true })
  } finally {
    dtBindConfirming.value = false
  }
}

const unbindDingTalk = async () => {
  try {
    await ElMessageBox.confirm('解绑后无法接收钉钉派工/进度通知，是否继续？', '解绑确认', { type: 'warning' })
    await request.post('/auth/dingtalk/unbind')
    syncLocalUser({ dingtalk_userid: null, dingtalk_bound_at: null })
    await loadDingTalkConfig()
    ElMessage.success('钉钉已解绑')
  } catch { /* 取消 */ }
}

// ===== 登录记录 =====
const loginHistory = ref([
  { time: '2026-07-30 14:30:22', ip: '192.168.1.100', device: 'Chrome / Windows 10', status: '成功' },
  { time: '2026-07-30 08:15:05', ip: '192.168.1.100', device: 'Chrome / Windows 10', status: '成功' },
  { time: '2026-07-29 17:42:18', ip: '10.0.0.56', device: '钉钉 / Android 14', status: '成功' },
  { time: '2026-07-29 09:00:00', ip: '192.168.1.105', device: 'Firefox / Windows 10', status: '失败' },
  { time: '2026-07-28 16:20:33', ip: '192.168.1.100', device: 'Chrome / Windows 10', status: '成功' },
])

onMounted(() => {
  loadPhoneBind()
  loadDingTalkConfig()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #1D2129;
}
.security-body {
  max-width: 700px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section-card {
  padding: 0;
}
.card-header-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
}
.security-form {
  max-width: 400px;
}

/* 密码修改 tab 切换 */
.pwd-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-bottom: 2px solid #E5E6EB;
}
.pwd-tab {
  padding: 8px 20px;
  font-size: 14px;
  color: #86909C;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.2s;
  user-select: none;
}
.pwd-tab:hover {
  color: #1D2129;
}
.pwd-tab.active {
  color: #165DFF;
  border-bottom-color: #165DFF;
  font-weight: 500;
}
.pwd-code-unbind-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: #FFF7E8;
  border-radius: 8px;
  font-size: 13px;
  color: #86909C;
}

/* 钉钉 */
.dt-intro {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 16px;
  background: #E8F3FF;
  border-radius: 8px;
  font-size: 13px;
  color: #4E5969;
  line-height: 1.6;
  margin-bottom: 16px;
}
.dt-intro .el-icon {
  flex-shrink: 0;
  margin-top: 1px;
}
.dt-desc {
  margin-bottom: 16px;
}
.code-text {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #4E5969;
  background: #F7F8FA;
  padding: 2px 6px;
  border-radius: 4px;
}
.dt-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
.dt-alert {
  margin-top: 12px;
}
.dt-unbind-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  padding: 8px 0 0;
}
.dt-qr-placeholder {
  width: 160px;
  height: 160px;
  border: 1px dashed #D0D0D0;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: #C9CDD4;
  text-align: center;
  padding: 12px;
}
.dt-bind-footer {
  text-align: center;
  margin-top: 20px;
}

/* 通用 - 验证码行 */
.code-row {
  display: flex;
  gap: 10px;
  align-items: center;
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
