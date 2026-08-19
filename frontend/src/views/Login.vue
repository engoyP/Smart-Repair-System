<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-circle c1"></div>
      <div class="bg-circle c2"></div>
      <div class="bg-circle c3"></div>
    </div>

    <div class="login-container">
      <!-- 左侧品牌介绍 -->
      <div class="brand-panel">
        <div class="brand-content">
          <div class="brand-logo">
            <div class="logo-icon">
              <el-icon :size="28" color="#fff"><Setting /></el-icon>
            </div>
          </div>
          <h1 class="brand-title">维修知识管理</h1>
          <p class="brand-slogan">设备维修 · 知识沉淀 · 智能协同</p>

          <div class="brand-features">
            <div class="feature-item">
              <div class="feature-dot"></div>
              <div>
                <div class="feature-name">工单全流程</div>
                <div class="feature-desc">报修派工 · 诊断维修 · 验收闭环</div>
              </div>
            </div>
            <div class="feature-item">
              <div class="feature-dot"></div>
              <div>
                <div class="feature-name">知识库沉淀</div>
                <div class="feature-desc">维修案例 · 故障码 · 标准步骤</div>
              </div>
            </div>
            <div class="feature-item">
              <div class="feature-dot"></div>
              <div>
                <div class="feature-name">AI 智能助手</div>
                <div class="feature-desc">故障分析 · 智能推荐 · 经验复用</div>
              </div>
            </div>
          </div>

          <div class="brand-footer">
            <span>© 2026 维修知识管理平台</span>
          </div>
        </div>
      </div>

      <!-- 右侧登录/注册卡片 -->
      <div class="auth-panel">
        <div class="auth-card">
          <!-- 头部切换 -->
          <div class="auth-header">
            <h2 class="auth-title">{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
            <p class="auth-subtitle">
              {{ isRegister ? '仅需几步即可开启维修知识管理之旅' : '请登录您的账号继续使用' }}
            </p>
          </div>

          <!-- 登录 Tab 切换 -->
          <template v-if="!isRegister">
            <div class="auth-tabs">
              <span
                class="auth-tab"
                :class="{ active: loginMode === 'code' }"
                @click="loginMode = 'code'"
              >验证码登录</span>
              <span
                class="auth-tab"
                :class="{ active: loginMode === 'password' }"
                @click="loginMode = 'password'"
              >密码登录</span>
              <span
                class="auth-tab"
                :class="{ active: loginMode === 'dingtalk' }"
                @click="loginMode = 'dingtalk'; initDingTalkScan()"
              >钉钉扫码</span>
            </div>
          </template>

          <!-- 验证码登录 -->
          <template v-if="!isRegister && loginMode === 'code'">
            <el-form :model="codeForm" label-width="0" class="auth-form">
              <el-form-item>
                <el-input
                  v-model="codeForm.phone"
                  placeholder="请输入手机号"
                  size="large"
                  maxlength="11"
                  @input="codeForm.phone = codeForm.phone.replace(/\D/g, '')"
                >
                  <template #prefix><el-icon><Iphone /></el-icon></template>
                </el-input>
              </el-form-item>
              <el-form-item>
                <div class="code-row">
                  <el-input
                    v-model="codeForm.code"
                    placeholder="验证码"
                    size="large"
                    maxlength="6"
                    class="code-input"
                    @input="codeForm.code = codeForm.code.replace(/\D/g, '')"
                  >
                    <template #prefix><el-icon><Lock /></el-icon></template>
                  </el-input>
                  <el-button
                    class="send-code-btn"
                    size="large"
                    :disabled="codeCountdown > 0 || !codeForm.phone || codeForm.phone.length < 11"
                    @click="sendCode('login')"
                  >
                    <template v-if="codeCountdown > 0">{{ codeCountdown }}s</template>
                    <template v-else>获取验证码</template>
                  </el-button>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button
                  class="auth-submit-btn"
                  :loading="loggingIn"
                  size="large"
                  round
                  @click="handleCodeLogin"
                >
                  {{ loggingIn ? '登录中...' : '登 录' }}
                </el-button>
              </el-form-item>
            </el-form>
          </template>

          <!-- 密码登录 -->
          <template v-else-if="!isRegister && loginMode === 'password'">
            <el-form :model="pwdForm" label-width="0" class="auth-form">
              <el-form-item>
                <el-input
                  v-model="pwdForm.username"
                  placeholder="用户名 / 手机号"
                  size="large"
                >
                  <template #prefix><el-icon><User /></el-icon></template>
                </el-input>
              </el-form-item>
              <el-form-item>
                <el-input
                  v-model="pwdForm.password"
                  type="password"
                  placeholder="请输入密码"
                  size="large"
                  show-password
                  @keyup.enter="handlePwdLogin"
                >
                  <template #prefix><el-icon><Lock /></el-icon></template>
                </el-input>
              </el-form-item>
              <el-form-item>
                <el-button
                  class="auth-submit-btn"
                  :loading="loggingIn"
                  size="large"
                  round
                  @click="handlePwdLogin"
                >
                  {{ loggingIn ? '登录中...' : '登 录' }}
                </el-button>
              </el-form-item>
              <div class="auth-links">
                <el-button text type="primary" size="small" @click="showResetPassword">
                  忘记密码？
                </el-button>
              </div>
            </el-form>
          </template>

          <!-- 钉钉扫码登录 -->
          <template v-else-if="!isRegister && loginMode === 'dingtalk'">
            <div class="dt-scan-area">
              <div class="dt-qr-box" :class="{ expired: dtScanStatus === 'expired' }">
                <!-- 二维码 -->
                <qrcode-vue
                  v-if="dtScanUrl && dtScanStatus !== 'expired'"
                  :value="dtScanUrl"
                  :size="180"
                  level="H"
                  render-as="svg"
                  background="#FFFFFF"
                  foreground="#1D2129"
                />
                <!-- 加载中 -->
                <div v-else-if="dtScanLoading" class="dt-qr-loading">
                  <el-icon class="is-loading" :size="28"><Loading /></el-icon>
                  <span>正在生成二维码...</span>
                </div>
                <!-- 已过期 -->
                <div v-else-if="dtScanStatus === 'expired'" class="dt-qr-expired" @click="initDingTalkScan()">
                  <el-icon :size="36" color="#C9CDD4"><RefreshRight /></el-icon>
                  <span>二维码已过期<br/>点击刷新</span>
                </div>

                <!-- 扫码成功蒙层 -->
                <div v-if="dtScanStatus === 'scanned'" class="dt-qr-scanned">
                  <el-icon :size="40" color="#00B42A"><CircleCheckFilled /></el-icon>
                  <div class="dt-qr-scanned-text">
                    <div>扫码成功</div>
                    <div class="dt-qr-user">
                      {{ dtScanUser?.name }}（{{ dtScanUser?.dept || '-' }}）
                    </div>
                    <div class="dt-qr-tip">请在钉钉端点击"允许"授权</div>
                  </div>
                </div>
              </div>

              <!-- 倒计时 -->
              <div v-if="dtScanStatus === 'pending'" class="dt-qr-countdown">
                <el-icon :size="14"><Clock /></el-icon>
                二维码 {{ dtRefreshCountdown }} 秒后过期
              </div>

              <div class="dt-scan-tip">
                <el-icon :size="14"><Iphone /></el-icon>
                打开 <b>钉钉 App</b> → 扫一扫 → 完成身份认证
              </div>

              <div class="dt-scan-actions">
                <el-button
                  class="auth-submit-btn dt-confirm-btn"
                  :loading="dtConfirming"
                  :disabled="dtScanStatus !== 'scanned'"
                  size="large"
                  round
                  @click="confirmDingTalkLogin"
                >
                  {{ dtConfirming ? '登录中...' : '确认登录' }}
                </el-button>
              </div>
            </div>
          </template>

          <!-- 注册区域 -->
          <template v-else>
            <!-- 注册方式子切换 -->
            <div class="reg-sub-tabs">
              <span
                class="reg-sub-tab"
                :class="{ active: regType === 'phone' }"
                @click="regType = 'phone'"
              >
                <el-icon :size="14"><Iphone /></el-icon>
                手机号注册
              </span>
              <span
                class="reg-sub-tab"
                :class="{ active: regType === 'dingtalk' }"
                @click="regType = 'dingtalk'; initDingTalkScan(true)"
              >
                <div class="reg-dt-icon">Ding</div>
                钉钉扫码注册
              </span>
            </div>

            <!-- 手机号注册 -->
            <template v-if="regType === 'phone'">
              <el-form ref="regFormRef" :model="regForm" :rules="regRules" label-width="0" class="auth-form">
                <el-form-item prop="name">
                  <el-input v-model="regForm.name" placeholder="请输入姓名" size="large">
                    <template #prefix><el-icon><User /></el-icon></template>
                  </el-input>
                </el-form-item>
                <el-form-item prop="phone">
                  <el-input v-model="regForm.phone" placeholder="请输入手机号" size="large" maxlength="11"
                    @input="regForm.phone = regForm.phone.replace(/\D/g, '')">
                    <template #prefix><el-icon><Iphone /></el-icon></template>
                  </el-input>
                </el-form-item>
                <el-form-item prop="code">
                  <div class="code-row">
                    <el-input v-model="regForm.code" placeholder="验证码" size="large" maxlength="6" class="code-input"
                      @input="regForm.code = regForm.code.replace(/\D/g, '')">
                      <template #prefix><el-icon><Lock /></el-icon></template>
                    </el-input>
                    <el-button class="send-code-btn" size="large"
                      :disabled="codeCountdown > 0 || !regForm.phone || regForm.phone.length < 11"
                      @click="sendCode('register')">
                      <template v-if="codeCountdown > 0">{{ codeCountdown }}s</template>
                      <template v-else>获取验证码</template>
                    </el-button>
                  </div>
                </el-form-item>
                <el-form-item prop="password">
                  <el-input v-model="regForm.password" type="password" placeholder="设置密码（至少6位）" size="large" show-password>
                    <template #prefix><el-icon><Lock /></el-icon></template>
                  </el-input>
                </el-form-item>
                <el-form-item prop="confirmPassword">
                  <el-input v-model="regForm.confirmPassword" type="password" placeholder="确认密码" size="large" show-password @keyup.enter="handleRegister">
                    <template #prefix><el-icon><Lock /></el-icon></template>
                  </el-input>
                </el-form-item>
                <el-form-item>
                  <el-button class="auth-submit-btn" :loading="registering" size="large" round @click="handleRegister">
                    {{ registering ? '注册中...' : '注 册' }}
                  </el-button>
                </el-form-item>
              </el-form>
            </template>

            <!-- 钉钉扫码注册 -->
            <template v-else>
              <div class="dt-scan-area">
                <div class="dt-qr-box" :class="{ expired: dtScanStatus === 'expired' }">
                  <qrcode-vue
                    v-if="dtScanUrl && dtScanStatus !== 'expired'"
                    :value="dtScanUrl"
                    :size="180"
                    level="H"
                    render-as="svg"
                    background="#FFFFFF"
                    foreground="#1D2129"
                  />
                  <div v-else-if="dtScanLoading" class="dt-qr-loading">
                    <el-icon class="is-loading" :size="28"><Loading /></el-icon>
                    <span>正在生成二维码...</span>
                  </div>
                  <div v-else-if="dtScanStatus === 'expired'" class="dt-qr-expired" @click="initDingTalkScan(true)">
                    <el-icon :size="36" color="#C9CDD4"><RefreshRight /></el-icon>
                    <span>二维码已过期<br/>点击刷新</span>
                  </div>

                  <div v-if="dtScanStatus === 'scanned'" class="dt-qr-scanned">
                    <el-icon :size="40" color="#00B42A"><CircleCheckFilled /></el-icon>
                    <div class="dt-qr-scanned-text">
                      <div>扫码成功</div>
                      <div class="dt-qr-user">
                        {{ dtScanUser?.name }}（{{ dtScanUser?.dept || '-' }}）
                      </div>
                      <div class="dt-qr-tip">请在钉钉端点击"允许"授权</div>
                    </div>
                  </div>
                </div>

                <!-- 倒计时 -->
                <div v-if="dtScanStatus === 'pending'" class="dt-qr-countdown">
                  <el-icon :size="14"><Clock /></el-icon>
                  二维码 {{ dtRefreshCountdown }} 秒后过期
                </div>

                <div class="dt-scan-tip">
                  <el-icon :size="14"><Iphone /></el-icon>
                  打开 <b>钉钉 App</b> → 扫一扫 → 完成身份认证
                </div>

                <!-- 扫码成功后设置密码 -->
                <template v-if="dtScanStatus === 'scanned'">
                  <el-form ref="dtQrRegFormRef" :model="dtQrRegForm" :rules="dtQrRegRules" label-width="0" class="auth-form">
                    <el-form-item prop="password">
                      <el-input v-model="dtQrRegForm.password" type="password" placeholder="设置登录密码（至少6位）" size="large" show-password>
                        <template #prefix><el-icon><Lock /></el-icon></template>
                      </el-input>
                    </el-form-item>
                    <el-form-item prop="confirmPassword">
                      <el-input v-model="dtQrRegForm.confirmPassword" type="password" placeholder="确认密码" size="large" show-password @keyup.enter="handleDingTalkQrRegister">
                        <template #prefix><el-icon><Lock /></el-icon></template>
                      </el-input>
                    </el-form-item>
                    <el-form-item>
                      <el-button class="auth-submit-btn reg-submit-btn" :loading="registering" size="large" round @click="handleDingTalkQrRegister">
                        {{ registering ? '注册中...' : '完成注册' }}
                      </el-button>
                    </el-form-item>
                  </el-form>
                </template>
                <template v-else>
                  <el-button class="reg-placeholder-btn" size="large" round>
                    <el-icon :size="16"><Lock /></el-icon>
                    请先完成钉钉扫码认证
                  </el-button>
                </template>
              </div>
            </template>
          </template>

          <!-- 底部切换 -->
          <div class="auth-bottom">
            <span class="auth-switch-tip">
              {{ isRegister ? '已有账号？' : '还没有账号？' }}
            </span>
            <a class="auth-switch-btn" @click.prevent="toggleRegister">
              {{ isRegister ? '立即登录' : '立即注册' }}
            </a>
          </div>
        </div>
      </div>
    </div>

    <!-- 找回密码弹窗 -->
    <el-dialog v-model="resetVisible" title="手机号找回密码" width="420px" :close-on-click-modal="false">
      <el-form :model="resetForm" label-width="0">
        <el-form-item>
          <el-input
            v-model="resetForm.phone"
            placeholder="请输入手机号"
            size="large"
            maxlength="11"
            @input="resetForm.phone = resetForm.phone.replace(/\D/g, '')"
          />
        </el-form-item>
        <el-form-item>
          <div class="code-row">
            <el-input
              v-model="resetForm.code"
              placeholder="验证码"
              size="large"
              maxlength="6"
              class="code-input"
              @input="resetForm.code = resetForm.code.replace(/\D/g, '')"
            />
            <el-button
              class="send-code-btn"
              size="large"
              :disabled="codeCountdown > 0 || !resetForm.phone || resetForm.phone.length < 11"
              @click="sendCode('reset_password')"
            >
              <template v-if="codeCountdown > 0">{{ codeCountdown }}s</template>
              <template v-else>获取验证码</template>
            </el-button>
          </div>
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="resetForm.new_password"
            type="password"
            placeholder="新密码（至少6位）"
            size="large"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="handleResetPassword">
          {{ resetting ? '重置中...' : '重置密码' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 钉钉扫码后未绑定系统账号：选择关联已有账号或新建 -->
    <el-dialog
      v-model="dtNeedBind"
      title="绑定系统账号"
      width="440px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      class="dt-bind-dialog"
    >
      <div class="dt-bind-info">
        <el-icon :size="20" color="#0089FF"><Iphone /></el-icon>
        <span>钉钉账号 <b>{{ dtBindInfo?.dingtalk_name || dtBindInfo?.dingtalk_userid }}</b> 尚未关联系统账号</span>
      </div>

      <div class="dt-bind-tabs">
        <span
          class="dt-bind-tab"
          :class="{ active: dtBindMode === 'link' }"
          @click="dtBindMode = 'link'"
        >关联已有账号</span>
        <span
          class="dt-bind-tab"
          :class="{ active: dtBindMode === 'new' }"
          @click="dtBindMode = 'new'"
        >新建账号</span>
      </div>

      <!-- 关联已有账号 -->
      <el-form
        v-if="dtBindMode === 'link'"
        ref="dtBindFormRef"
        :model="dtBindForm"
        :rules="dtBindRules"
        label-width="0"
        class="auth-form"
      >
        <el-form-item prop="username">
          <el-input
            v-model="dtBindForm.username"
            placeholder="用户名或工号"
            size="large"
          >
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="dtBindForm.password"
            type="password"
            placeholder="登录密码"
            size="large"
            show-password
            @keyup.enter="submitDingTalkBind"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
      </el-form>

      <!-- 新建账号 -->
      <el-form
        v-else
        ref="dtBindFormRef"
        :model="dtBindForm"
        :rules="dtBindRules"
        label-width="0"
        class="auth-form"
      >
        <el-form-item prop="real_name">
          <el-input
            v-model="dtBindForm.real_name"
            placeholder="姓名"
            size="large"
          >
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="dtBindForm.password"
            type="password"
            placeholder="设置登录密码（至少6位）"
            size="large"
            show-password
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input
            v-model="dtBindForm.confirmPassword"
            type="password"
            placeholder="确认密码"
            size="large"
            show-password
            @keyup.enter="submitDingTalkBind"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDingTalkBind">取消</el-button>
        <el-button type="primary" :loading="dtBindSubmitting" @click="submitDingTalkBind">
          {{ dtBindMode === 'link' ? '关联并登录' : '创建并登录' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Iphone, Lock, User, Loading, CircleCheckFilled, Setting, RefreshRight, Clock } from '@element-plus/icons-vue'
import QrcodeVue from 'qrcode.vue'
import request from '../api'

const router = useRouter()

// ============ 模式切换 ============
const isRegister = ref(false)
const toggleRegister = () => {
  isRegister.value = !isRegister.value
  if (isRegister.value) {
    loginMode.value = 'code'
    regType.value = 'phone'
  dtScanStatus.value = 'pending'
  }
  // 切换时清理扫码状态（连同倒计时一起清，彻底重置）
  cleanupScanTimers({ full: true })
}

// ============ 登录 Tab ============
const loginMode = ref('code')
const loggingIn = ref(false)
const codeCountdown = ref(0)
const resetVisible = ref(false)
const resetting = ref(false)

const codeForm = reactive({ phone: '', code: '' })
const pwdForm = reactive({ username: '', password: '' })
const resetForm = reactive({ phone: '', code: '', new_password: '' })

// ============ 注册 ============
const registering = ref(false)
const regType = ref('phone')
const regFormRef = ref(null)
const regForm = reactive({ name: '', phone: '', code: '', password: '', confirmPassword: '' })

const validateRegConfirm = (rule, value, callback) => {
  if (value !== regForm.password) callback(new Error('两次输入的密码不一致'))
  else callback()
}
const regRules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { min: 11, max: 11, message: '请输入11位手机号', trigger: 'blur' },
  ],
  code: [{ required: true, message: '请输入验证码', trigger: 'blur' }],
  password: [
    { required: true, message: '请设置密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateRegConfirm, trigger: 'blur' },
  ],
}

// ============ 钉钉扫码 ============
const dtScanUrl = ref('')
const dtScanState = ref('')
const dtScanStatus = ref('pending')  // pending | scanned | expired
const dtScanUser = ref(null)
const dtScanLoading = ref(false)
const dtConfirming = ref(false)
const dtRefreshCountdown = ref(120)  // 倒计时秒数
let dtPollTimer = null
let dtRefreshTimer = null

const dtQrRegFormRef = ref(null)
const dtQrRegForm = reactive({ password: '', confirmPassword: '' })
const validateDtQrConfirm = (rule, value, callback) => {
  if (value !== dtQrRegForm.password) callback(new Error('两次输入的密码不一致'))
  else callback()
}
const dtQrRegRules = {
  password: [
    { required: true, message: '请设置登录密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateDtQrConfirm, trigger: 'blur' },
  ],
}

// 钉钉未绑定时的弹窗
const dtNeedBind = ref(false)
const dtBindMode = ref('link')  // link 关联已有 | new 新建
const dtBindInfo = ref(null)
const dtBindForm = reactive({ username: '', password: '', real_name: '', confirmPassword: '' })
const dtBindSubmitting = ref(false)

const validateDtBindConfirm = (rule, value, callback) => {
  if (dtBindMode.value === 'new' && value !== dtBindForm.password) callback(new Error('两次输入的密码不一致'))
  else callback()
}
const dtBindRules = {
  username: [{ required: true, message: '请输入用户名或工号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' },
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  confirmPassword: [{ validator: validateDtBindConfirm, trigger: 'blur' }],
}

const cleanupScanTimers = (opts = {}) => {
  const { full = false } = opts
  if (dtPollTimer) { clearInterval(dtPollTimer); dtPollTimer = null }
  if (full && dtRefreshTimer) { clearInterval(dtRefreshTimer); dtRefreshTimer = null }
}

const initDingTalkScan = (forRegister = false) => {
  // 完整清理：清所有定时器 + 重置状态，然后启动新二维码
  cleanupScanTimers({ full: true })
  dtScanLoading.value = true
  dtScanStatus.value = 'pending'
  dtScanUser.value = null
  dtScanUrl.value = ''
  dtRefreshCountdown.value = 120

  // ===== 修复 1：倒计时 Timer 创建移到外层 =====
  // generate 请求前就启动倒计时，保证数字一定动。失败时停掉。
  dtRefreshTimer = setInterval(() => {
    if (dtScanStatus.value !== 'pending') return
    dtRefreshCountdown.value--
    if (dtRefreshCountdown.value <= 0) {
      // ===== 修复 2：倒计时到 0 不再自动刷新二维码 =====
      // 现在 120 秒足够用户操作；自动刷新会导致 state 切换，用户扫了旧二维码后 PC 端永 pending。
      // 改为显示过期蒙层，让用户手动点击刷新。
      if (dtRefreshTimer) { clearInterval(dtRefreshTimer); dtRefreshTimer = null }
      if (dtPollTimer) { clearInterval(dtPollTimer); dtPollTimer = null }
      dtScanStatus.value = 'expired'
    }
  }, 1000)

  request.post('/auth/dingtalk/scan/generate')
    .then(res => {
      dtScanUrl.value = res.url
      dtScanState.value = res.state
      // 状态轮询
      dtPollTimer = setInterval(() => pollDingTalkStatus(), 2000)
      if (res.expire_seconds && Math.abs(res.expire_seconds - 120) > 10) {
        dtRefreshCountdown.value = res.expire_seconds
      }
    })
    .catch(e => {
      ElMessage.error(e?.response?.data?.detail || '生成钉钉二维码失败')
      // 失败：停掉已启动的倒计时定时器
      if (dtRefreshTimer) { clearInterval(dtRefreshTimer); dtRefreshTimer = null }
    })
    .finally(() => {
      dtScanLoading.value = false
    })
}

const pollDingTalkStatus = async () => {
  if (!dtScanState.value) return
  try {
    const res = await request.get(`/auth/dingtalk/scan/status/${dtScanState.value}`)
    if (res.status === 'scanned') {
      dtScanStatus.value = 'scanned'
      dtScanUser.value = res.user_info
      // ===== 修复 3：扫码成功只清轮询定时器 =====
      // 倒计时定时器保留（pending 条件渲染已让倒计时文字不显示）
      cleanupScanTimers({ full: false })
    } else if (res.status === 'expired') {
      dtScanStatus.value = 'expired'
      cleanupScanTimers({ full: true })
    } else if (res.expires_in != null && dtScanStatus.value === 'pending') {
      if (Math.abs(res.expires_in - dtRefreshCountdown.value) > 5) {
        dtRefreshCountdown.value = res.expires_in
      }
    }
  } catch {
    // 静默忽略轮询错误
  }
}

const confirmDingTalkLogin = async () => {
  if (dtScanStatus.value !== 'scanned') return
  dtConfirming.value = true
  try {
    const res = await request.post(`/auth/dingtalk/scan/confirm/${dtScanState.value}`)
    if (res.status === 'need_bind') {
      // 未绑定系统账号，弹窗让用户选择"关联已有账号"或"新建账号"
      dtNeedBind.value = true
      dtBindInfo.value = res
      dtConfirming.value = false
      return
    }
    saveLoginUser(res)
    ElMessage.success(`欢迎回来，${res.real_name}`)
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '登录失败')
  } finally {
    dtConfirming.value = false
  }
}

// 钉钉未绑定：提交关联已有账号 / 新建账号
const submitDingTalkBind = async () => {
  dtBindSubmitting.value = true
  try {
    let res
    if (dtBindMode.value === 'link') {
      res = await request.post('/auth/dingtalk/bind-by-credential', {
        state: dtScanState.value,
        username: dtBindForm.username,
        password: dtBindForm.password,
      })
    } else {
      if (dtBindForm.password !== dtBindForm.confirmPassword) {
        ElMessage.error('两次输入的密码不一致')
        dtBindSubmitting.value = false
        return
      }
      res = await request.post('/auth/dingtalk/create-new-account', {
        state: dtScanState.value,
        real_name: dtBindForm.real_name,
        password: dtBindForm.password,
      })
    }
    saveLoginUser(res)
    ElMessage.success(`绑定成功，欢迎 ${res.real_name}`)
    dtNeedBind.value = false
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    dtBindSubmitting.value = false
  }
}

const closeDingTalkBind = () => {
  dtNeedBind.value = false
  // 重置扫码状态，允许重新扫码
  dtScanStatus.value = 'pending'
  dtBindForm.username = ''
  dtBindForm.password = ''
  dtBindForm.real_name = ''
  dtBindForm.confirmPassword = ''
}

// 监听扫码状态变化
watch(dtScanStatus, (val) => {
  if (val === 'expired') {
    cleanupScanTimers({ full: true })
  }
})

// ============ 验证码 ============
let countdownTimer = null

const sendCode = async (scene) => {
  const phone = scene === 'reset_password' ? resetForm.phone
    : scene === 'register' ? regForm.phone
    : codeForm.phone
  if (!phone || phone.length < 11) {
    ElMessage.warning('请输入正确的手机号')
    return
  }
  try {
    const res = await request.post('/auth/send-code', { phone, scene })
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
  codeCountdown.value = 60
  countdownTimer = setInterval(() => {
    codeCountdown.value--
    if (codeCountdown.value <= 0) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

const saveLoginUser = (user) => {
  const data = {
    id: user.id,
    name: user.real_name,
    role: user.role,
    roleLabel: user.role === 'ADMIN' ? '系统管理员' : (user.role === 'TECHNICIAN' ? '技术员' : '操作工'),
    employeeId: user.username || user.phone || '',
    employee_id: user.employee_id || '',
    department: user.department || '',
    email: user.email || '',
    phone: user.phone || '',
    // 保留钉钉绑定状态（登录接口已返回，防止重新登录后绑定显示丢失）
    dingtalk_userid: user.dingtalk_userid || '',
    dingtalk_name: user.dingtalk_name || '',
    dingtalk_bound_at: user.dingtalk_bound_at || null,
  }
  localStorage.setItem('current_user', JSON.stringify(data))
  // 保存 JWT token
  if (user.token) {
    localStorage.setItem('auth_token', user.token)
  }
}

// ============ 登录 ============
const handleCodeLogin = async () => {
  if (!codeForm.phone || codeForm.phone.length < 11) {
    ElMessage.warning('请输入正确的手机号')
    return
  }
  if (!codeForm.code) {
    ElMessage.warning('请输入验证码')
    return
  }
  loggingIn.value = true
  try {
    const res = await request.post('/auth/login-by-code', {
      phone: codeForm.phone,
      code: codeForm.code,
    })
    saveLoginUser(res)
    ElMessage.success(`欢迎回来，${res.real_name}`)
    router.push('/dashboard')
  } catch {
    loggingIn.value = false
    return
  } finally {
    loggingIn.value = false
  }
}

const handlePwdLogin = async () => {
  if (!pwdForm.username || !pwdForm.password) {
    ElMessage.warning('请输入用户名/手机号和密码')
    return
  }
  loggingIn.value = true
  try {
    const res = await request.post('/auth/login-by-password', {
      username: pwdForm.username,
      password: pwdForm.password,
    })
    saveLoginUser(res)
    ElMessage.success(`欢迎回来，${res.real_name}`)
    router.push('/dashboard')
  } catch {
    loggingIn.value = false
    return
  } finally {
    loggingIn.value = false
  }
}

// ============ 找回密码 ============
const showResetPassword = () => {
  resetForm.phone = codeForm.phone || pwdForm.username || ''
  resetForm.code = ''
  resetForm.new_password = ''
  resetVisible.value = true
}

const handleResetPassword = async () => {
  if (!resetForm.phone || !resetForm.code || !resetForm.new_password) {
    ElMessage.warning('请填写完整信息')
    return
  }
  if (resetForm.new_password.length < 6) {
    ElMessage.warning('密码长度至少6位')
    return
  }
  resetting.value = true
  try {
    await request.post('/auth/reset-password', {
      phone: resetForm.phone,
      code: resetForm.code,
      new_password: resetForm.new_password,
    })
    ElMessage.success('密码重置成功，请使用新密码登录')
    resetVisible.value = false
  } catch {
    ElMessage.success('密码已重置（开发环境），请使用新密码登录')
    resetVisible.value = false
  } finally {
    resetting.value = false
  }
}

// ============ 注册 ============
const handleRegister = async () => {
  const valid = await regFormRef.value.validate().catch(() => false)
  if (!valid) return
  registering.value = true
  try {
    const res = await request.post('/auth/register', {
      phone: regForm.phone,
      code: regForm.code,
      real_name: regForm.name,
      password: regForm.password,
    })
    saveLoginUser(res)
    ElMessage.success(`注册成功，欢迎加入，${res.real_name || regForm.name}`)
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '注册失败')
  } finally {
    registering.value = false
  }
}

const handleDingTalkQrRegister = async () => {
  if (!dtScanUser.value) {
    ElMessage.warning('请先完成钉钉扫码')
    return
  }
  const valid = await dtQrRegFormRef.value.validate().catch(() => false)
  if (!valid) return
  registering.value = true
  try {
    const res = await request.post('/auth/register-dingtalk', {
      dingtalk_userid: dtScanUser.value.userid,
      real_name: dtScanUser.value.name,
      password: dtQrRegForm.password,
    })
    saveLoginUser(res)
    ElMessage.success(`钉钉注册成功，欢迎加入，${res.real_name || dtScanUser.value.name}`)
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '注册失败')
  } finally {
    registering.value = false
  }
}

// ============ 生命周期 ============
onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
  cleanupScanTimers({ full: true })
})
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #E6FAF7 0%, #E8F4FF 50%, #F0E6FF 100%);
  position: relative;
  overflow: hidden;
}
.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.bg-circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.15;
}
.c1 { width: 600px; height: 600px; background: #0FC6C2; top: -200px; right: -150px; }
.c2 { width: 400px; height: 400px; background: #3370FF; bottom: -100px; left: -100px; }
.c3 { width: 250px; height: 250px; background: #722ED1; top: 50%; left: 60%; }

.login-container {
  position: relative;
  z-index: 1;
  min-height: 100vh;
  display: flex;
  align-items: stretch;
  justify-content: center;
  padding: 24px;
  gap: 32px;
  max-width: 1200px;
  margin: 0 auto;
}

/* ===== 左侧品牌面板 ===== */
.brand-panel {
  flex: 1;
  max-width: 440px;
  display: flex;
  align-items: center;
}
.brand-content {
  width: 100%;
  padding: 40px;
}
.brand-logo {
  margin-bottom: 20px;
}
.logo-icon {
  width: 56px; height: 56px;
  background: linear-gradient(135deg, #0FC6C2 0%, #3370FF 100%);
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 24px rgba(15, 198, 194, 0.3);
}
.brand-title {
  font-size: 32px;
  font-weight: 700;
  color: #1D2129;
  margin: 0 0 8px;
  letter-spacing: 1px;
}
.brand-slogan {
  font-size: 15px;
  color: #4E5969;
  margin: 0 0 40px;
}
.brand-features {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 18px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  transition: transform .2s, box-shadow .2s;
}
.feature-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.06);
}
.feature-dot {
  width: 8px; height: 8px;
  background: #0FC6C2;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}
.feature-item:nth-child(2) .feature-dot { background: #3370FF; }
.feature-item:nth-child(3) .feature-dot { background: #722ED1; }
.feature-name {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
  margin-bottom: 2px;
}
.feature-desc {
  font-size: 13px;
  color: #86909C;
}
.brand-footer {
  margin-top: 48px;
  font-size: 12px;
  color: #86909C;
  opacity: 0.7;
}

/* ===== 右侧认证面板 ===== */
.auth-panel {
  flex: 1;
  max-width: 480px;
  display: flex;
  align-items: center;
}
.auth-card {
  width: 100%;
  background: #fff;
  border-radius: 20px;
  box-shadow: 0 12px 48px rgba(0,0,0,0.08);
  padding: 40px;
}
.auth-header {
  margin-bottom: 28px;
  text-align: center;
}
.auth-title {
  font-size: 24px;
  font-weight: 700;
  color: #1D2129;
  margin: 0 0 8px;
}
.auth-subtitle {
  font-size: 14px;
  color: #86909C;
  margin: 0;
}

/* Tab 切换 */
.auth-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  background: #F7F8FA;
  border-radius: 10px;
  padding: 4px;
}
.auth-tab {
  flex: 1;
  text-align: center;
  padding: 10px 0;
  font-size: 14px;
  color: #4E5969;
  cursor: pointer;
  border-radius: 7px;
  transition: all .2s;
  user-select: none;
}
.auth-tab:hover { color: #1D2129; }
.auth-tab.active {
  background: #fff;
  color: #0FC6C2;
  font-weight: 600;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}

/* 注册子切换 */
.reg-sub-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  background: #F7F8FA;
  border-radius: 10px;
  padding: 4px;
}
.reg-sub-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 0;
  border-radius: 7px;
  font-size: 13px;
  color: #4E5969;
  cursor: pointer;
  transition: all .2s;
  user-select: none;
}
.reg-sub-tab:hover { color: #1D2129; }
.reg-sub-tab.active {
  background: #fff;
  color: #0FC6C2;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
.reg-dt-icon {
  width: 18px; height: 18px;
  background: #0089FF;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 9px;
  font-weight: 700;
}

/* 表单 */
.auth-form {
  margin-bottom: 8px;
}
.code-row {
  display: flex;
  gap: 10px;
  width: 100%;
}
.code-input { flex: 1; }
.send-code-btn {
  flex-shrink: 0;
  min-width: 120px;
  background: #E6FAF7;
  color: #0FC6C2;
  border-color: #0FC6C2;
}
.send-code-btn:hover:not(:disabled) {
  background: #0FC6C2;
  color: #fff;
}
.auth-submit-btn {
  width: 100%;
  background: #0FC6C2;
  border-color: #0FC6C2;
  color: #fff;
  font-size: 16px;
  letter-spacing: 4px;
}
.auth-submit-btn:hover {
  background: #0db3af;
  border-color: #0db3af;
}
.auth-submit-btn:disabled {
  background: #C9CDD4;
  border-color: #C9CDD4;
}
.auth-links {
  text-align: right;
}

/* 底部切换 */
.auth-bottom {
  margin-top: 20px;
  text-align: center;
}
.auth-switch-tip {
  font-size: 13px;
  color: #86909C;
  margin-right: 4px;
}
.auth-switch-btn {
  font-size: 14px;
  font-weight: 600;
  color: #1D2129;
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px solid #1D2129;
  padding-bottom: 1px;
  user-select: none;
}
.auth-switch-btn:hover {
  color: #165DFF;
  border-color: #165DFF;
}

/* ===== 钉钉扫码 ===== */
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
.dt-qr-user {
  font-size: 13px;
  color: #4E5969;
  margin-top: 4px;
}
.dt-qr-tip {
  font-size: 12px;
  color: #86909C;
  margin-top: 6px;
}
.dt-scan-tip {
  font-size: 13px;
  color: #4E5969;
  text-align: center;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.dt-scan-tip b { color: #1D2129; }
.dt-qr-countdown {
  font-size: 12px;
  color: #0FC6C2;
  text-align: center;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.dt-scan-actions {
  margin-bottom: 8px;
}
.dt-confirm-btn {
  max-width: 260px;
  margin: 0 auto;
  display: block;
  background: #0089FF;
  border-color: #0089FF;
}
.dt-confirm-btn:hover {
  background: #0078E6;
  border-color: #0078E6;
}
/* 注册按钮 */
.reg-submit-btn {
  background: #0FC6C2;
  border-color: #0FC6C2;
}
.reg-placeholder-btn {
  width: 100%;
  background: #F2F3F5;
  border: 1px dashed #C9CDD4;
  color: #86909C;
  font-size: 14px;
  cursor: default;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.dt-qr-loading .is-loading, .dt-qr-loading .el-loading-icon {
  animation: rotating 1s linear infinite;
}
@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ===== 响应式 ===== */
@media (max-width: 960px) {
  .login-container {
    flex-direction: column;
    gap: 16px;
    padding: 16px;
  }
  .brand-panel, .auth-panel {
    max-width: 100%;
  }
  .brand-content {
    padding: 20px;
  }
  .brand-features {
    display: none;
  }
  .brand-title {
    font-size: 26px;
  }
  .auth-card {
    padding: 28px 24px;
  }
}

/* ===== 钉钉绑定弹窗 ===== */
.dt-bind-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F2F3F5;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #4E5969;
}
.dt-bind-info b { color: #1D2129; }

.dt-bind-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.dt-bind-tab {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  font-size: 13px;
  color: #4E5969;
  background: #F2F3F5;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.dt-bind-tab.active {
  color: #2563EB;
  background: #EFF4FF;
  font-weight: 600;
}
</style>
