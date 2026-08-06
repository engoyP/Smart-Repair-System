<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">个人设置</h2>
    </div>

    <div class="profile-body">
      <!-- 头像区域 -->
      <el-card shadow="never" class="profile-card">
        <div class="avatar-section">
          <el-avatar :size="80" icon="UserFilled" class="profile-avatar" />
          <div class="avatar-info">
            <h3>{{ form.real_name || '管理员' }}</h3>
            <span class="role-badge">{{ roleLabel }}</span>
            <p class="dept-text">{{ form.department || '维修技术部' }}</p>
          </div>
        </div>
      </el-card>

      <!-- 基本信息 -->
      <el-card shadow="never" class="form-card">
        <template #header>
          <span class="card-title">基本信息</span>
        </template>
        <el-form :model="form" label-width="100px" class="profile-form">
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="姓名">
                <el-input v-model="form.real_name" placeholder="请输入姓名" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="工号">
                <el-input v-model="form.employee_id" disabled />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="部门">
                <el-input v-model="form.department" placeholder="请输入部门" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="职位">
                <el-input v-model="form.title" placeholder="请输入职位" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="邮箱">
                <el-input v-model="form.email" placeholder="请输入邮箱" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="手机号">
                <el-input v-model="form.phone" placeholder="请输入手机号" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="入职日期">
                <el-date-picker
                  v-model="form.join_date"
                  type="date"
                  placeholder="选择日期"
                  style="width:100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="技能等级">
                <el-select v-model="form.skill_level" style="width:100%">
                  <el-option label="初级" value="JUNIOR" />
                  <el-option label="中级" value="MIDDLE" />
                  <el-option label="高级" value="SENIOR" />
                  <el-option label="专家" value="EXPERT" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="个人简介">
            <el-input v-model="form.bio" type="textarea" :rows="3" placeholder="请输入个人简介" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="handleSave">
              {{ saving ? '保存中...' : '保存修改' }}
            </el-button>
            <el-button @click="handleReset">重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 第三方账号 -->
      <el-card shadow="never" class="form-card">
        <template #header>
          <span class="card-title">第三方账号</span>
        </template>
        <div class="third-party-section">
          <div class="tp-item">
            <div class="tp-icon dingtalk-icon">Ding</div>
            <div class="tp-info">
              <div class="tp-name">钉钉账号</div>
              <div class="tp-desc" v-if="dtBound">
                <span class="tp-status bound">已绑定</span>
                <span class="tp-detail">钉钉用户：{{ form.dingtalk_userid }}</span>
                <span class="tp-detail" v-if="form.dingtalk_bound_at">
                  绑定时间：{{ formatTime(form.dingtalk_bound_at) }}
                </span>
              </div>
              <div class="tp-desc" v-else>
                <span class="tp-status unbound">未绑定</span>
                <span class="tp-detail">绑定后可通过钉钉扫码登录系统、接收派工通知</span>
              </div>
            </div>
            <div class="tp-action">
              <el-button
                v-if="dtBound"
                type="danger"
                plain
                size="small"
                :loading="unbinding"
                @click="handleUnbindDingTalk"
              >解绑</el-button>
              <span v-else class="tp-hint">请通过钉钉扫码登录完成绑定</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const roleLabelMap = { ADMIN: '系统管理员', TECHNICIAN: '技术员', WORKER: '操作工', SUPERVISOR: '主管' }

const form = reactive({
  real_name: '管理员',
  employee_id: 'EMP001',
  department: '维修技术部',
  title: '高级工程师',
  email: 'admin@company.com',
  phone: '138-0000-0001',
  join_date: null,
  skill_level: 'SENIOR',
  bio: '',
  role: 'ADMIN',
  dingtalk_userid: '',
  dingtalk_bound_at: null,
})

const roleLabel = computed(() => roleLabelMap[form.role] || form.role)
const saving = ref(false)
const unbinding = ref(false)
const dtBound = computed(() => !!form.dingtalk_userid)

const formatTime = (t) => {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

const loadProfile = () => {
  try {
    const saved = localStorage.getItem('current_user')
    if (saved) {
      const data = JSON.parse(saved)
      Object.keys(form).forEach(k => {
        if (data[k] !== undefined) form[k] = data[k]
      })
    }
  } catch { /* ignore */ }
}

const handleSave = async () => {
  saving.value = true
  try {
    // 从 localStorage 获取用户 id
    const existing = localStorage.getItem('current_user')
    const existingData = existing ? JSON.parse(existing) : {}
    const userId = existingData.id
    if (userId) {
      // 调用后端接口更新 users 表（名字同步到工单）
      await request.put(`/users/${userId}`, {
        real_name: form.real_name,
        department: form.department,
        title: form.title,
        email: form.email,
        phone: form.phone,
      })
    }
    // 更新 localStorage（基于现有数据，避免丢失 employee_id 等字段）
    Object.keys(form).forEach(k => { existingData[k] = form[k] })
    existingData.name = form.real_name
    existingData.roleLabel = roleLabelMap[form.role] || form.role
    localStorage.setItem('current_user', JSON.stringify(existingData))
    ElMessage.success('个人信息已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleReset = () => {
  loadProfile()
  ElMessage.info('已恢复为上次保存的内容')
}

const handleUnbindDingTalk = async () => {
  try {
    await ElMessageBox.confirm('解绑后无法通过钉钉扫码登录和接收通知，确定解绑？', '解绑确认', {
      confirmButtonText: '确定解绑',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  unbinding.value = true
  try {
    await request.post('/auth/dingtalk/unbind')
    form.dingtalk_userid = ''
    form.dingtalk_bound_at = null
    // 同步到 localStorage
    const existing = localStorage.getItem('current_user')
    if (existing) {
      const data = JSON.parse(existing)
      data.dingtalk_userid = ''
      data.dingtalk_bound_at = null
      localStorage.setItem('current_user', JSON.stringify(data))
    }
    ElMessage.success('钉钉账号已解绑')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解绑失败')
  } finally {
    unbinding.value = false
  }
}

onMounted(() => {
  loadProfile()
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
.profile-body {
  max-width: 780px;
}
.profile-card {
  margin-bottom: 16px;
}
.avatar-section {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 8px 0;
}
.avatar-info h3 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
  color: #1D2129;
}
.role-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  background: #E6FAF7;
  color: #0FC6C2;
  margin-right: 10px;
}
.dept-text {
  display: inline;
  font-size: 13px;
  color: #86909C;
}
.form-card {
  padding: 0;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
}
.profile-form {
  max-width: 640px;
}

/* 第三方账号 */
.third-party-section {
  max-width: 640px;
}
.tp-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #F7F8FA;
  border-radius: 8px;
}
.tp-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: #FFFFFF;
  flex-shrink: 0;
}
.dingtalk-icon {
  background: #0089FF;
}
.tp-info {
  flex: 1;
}
.tp-name {
  font-size: 14px;
  font-weight: 600;
  color: #1D2129;
  margin-bottom: 4px;
}
.tp-desc {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.tp-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}
.tp-status.bound {
  color: #00B42A;
  background: #E8FFEA;
}
.tp-status.unbound {
  color: #86909C;
  background: #F2F3F5;
}
.tp-detail {
  font-size: 12px;
  color: #4E5969;
}
.tp-hint {
  font-size: 12px;
  color: #86909C;
}
</style>
