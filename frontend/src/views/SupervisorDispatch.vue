<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" circle @click="$router.back()" />
        <h2 class="page-title">派工中心</h2>
      </div>
    </div>

    <div class="dispatch-wrap">
      <el-card class="form-card" shadow="never">
        <!-- 提交失败时顶部展示的错误提示 -->
        <el-alert
          v-if="submitError"
          :title="submitError"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom: 16px;"
        />
        <el-form :model="form" ref="formRef" label-width="100px" :rules="rules">
          <el-form-item label="故障描述" prop="fault_description">
            <el-input
              v-model="form.fault_description"
              type="textarea"
              :rows="6"
              placeholder="简要描述设备目前的故障情况，有什么现象"
              maxlength="1000"
              show-word-limit
            />
          </el-form-item>

          <el-form-item label="现场图片">
            <el-upload
              v-model:file-list="fileList"
              list-type="picture-card"
              :auto-upload="false"
              :on-preview="handlePicturePreview"
              :on-remove="handleRemove"
              class="upload-area"
            >
              <el-icon :size="20"><Plus /></el-icon>
            </el-upload>
            <div class="upload-tip">Phase1暂未对接上传后端，仅做UI展示</div>
          </el-form-item>

          <el-form-item label="指派维修员" prop="technician_id">
            <el-select
              v-model="form.technician_id"
              filterable
              placeholder="选择维修员（可搜索姓名），默认按在手单最少优先"
              class="full-width"
            >
              <el-option
                v-for="t in technicianOptionsSorted"
                :key="t.id"
                :label="`${t.real_name}  [在手${t.current_workload_count}单] [今日${t.shift_label}] [近7天${t.recent7d_completed}单]`"
                :value="t.id"
                :disabled="t.is_on_leave"
              >
                <div class="tech-option-row">
                  <div class="tech-option-left">
                    <span class="tech-option-name">{{ t.real_name }}</span>
                    <span v-if="t.skills" class="tech-option-skills">· {{ t.skills }}</span>
                  </div>
                  <div class="tech-option-right">
                    <el-tag
                      v-if="t.is_on_leave"
                      type="danger"
                      size="small"
                      effect="dark"
                    >
                      请假中
                    </el-tag>
                    <el-tag
                      v-else-if="t.current_workload_count === 0"
                      type="success"
                      size="small"
                    >
                      ⚪ 在手 0 单（空闲）
                    </el-tag>
                    <el-tag
                      v-else-if="t.current_workload_count <= 2"
                      type="info"
                      size="small"
                    >
                      🟢 在手 {{ t.current_workload_count }} 单
                    </el-tag>
                    <el-tag v-else type="warning" size="small">
                      🟡 在手 {{ t.current_workload_count }} 单
                    </el-tag>
                    <el-tag size="small" type="primary" plain class="tech-tag-margin">
                      今日 {{ t.shift_label }}
                    </el-tag>
                    <el-tag size="small" effect="plain">
                      近7天 {{ t.recent7d_completed }} 单
                    </el-tag>
                  </div>
                </div>
              </el-option>
            </el-select>
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              @click="handleSubmit"
              :loading="submitting"
            >
              <el-icon style="margin-right:6px;"><Check /></el-icon>
              提交派工
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Plus, Check } from '@element-plus/icons-vue'
import request from '../api'
import { leaveSummary } from '../api/supervisor'

// 班次文字映射
const shiftTextMap = { MORNING: '早班', AFTERNOON: '中班', NIGHT: '晚班', ALL_DAY: '全天' }
function shiftText(s) { return shiftTextMap[s] || s || '未排班' }

// 当前时段（与后端 dispatch_agent 逻辑一致）
function getCurrentShift() {
  const h = new Date().getHours()
  if (h >= 8 && h <= 15) return 'MORNING'
  if (h >= 16 && h <= 23) return 'AFTERNOON'
  return 'NIGHT'
}

const router = useRouter()
const formRef = ref(null)
const submitting = ref(false)
const deviceLoading = ref(false)

// 提交失败时的错误信息（为空则不显示顶部 Alert）
const submitError = ref('')

// 维修员原始数据（从后端拉的）
const technicianOptionsRaw = ref([])
// 排序后的维修员选项：请假排最后 → 在手工单升序 → 近7天完成量降序 → 姓名
const technicianOptionsSorted = computed(() => {
  const list = [...(technicianOptionsRaw.value || [])]
  return list.sort((a, b) => {
    if (a.is_on_leave !== b.is_on_leave) return a.is_on_leave ? 1 : -1
    if ((a.current_workload_count || 0) !== (b.current_workload_count || 0)) {
      return (a.current_workload_count || 0) - (b.current_workload_count || 0)
    }
    if ((a.recent7d_completed || 0) !== (b.recent7d_completed || 0)) {
      return (b.recent7d_completed || 0) - (a.recent7d_completed || 0)
    }
    return (a.real_name || '').localeCompare(b.real_name || '', 'zh')
  })
})

const form = reactive({
  fault_description: '',
  technician_id: null,
  location: '',
  attachments: [],
})

const rules = {
  fault_description: [{ required: true, message: '请填写故障描述', trigger: 'blur' }],
  technician_id: [{ required: true, message: '请选择维修员', trigger: 'change' }],
}

const fileList = ref([])

// 获取维修员列表，并叠加今日排班/请假状态
const fetchTechnicians = async () => {
  try {
    const today = new Date().toISOString().slice(0, 10)
    const [techRes, todayDuty, leaveRes] = await Promise.all([
      request.get('/dispatch/technicians'),
      request.get('/duty-schedules/today'),
      leaveSummary(today)
    ])

    // 当前时段（用于判断半天请假）
    const currentShift = getCurrentShift()

    // 构建请假用户集合：全天请假 + 当前时段请假
    const leaveUserIds = new Set()
    for (const l of (leaveRes?.leaves || [])) {
      if (l.shift === 'ALL_DAY' || l.shift === currentShift) {
        leaveUserIds.add(l.user_id)
      }
    }

    // 构建 user_id → 班次标签 映射（从今日排班提取，排除请假记录）
    const userShiftMap = {}
    for (const shift of ['MORNING', 'AFTERNOON', 'NIGHT']) {
      for (const d of (todayDuty[shift] || [])) {
        if (d.schedule_type !== 'LEAVE' && !userShiftMap[d.user_id]) {
          userShiftMap[d.user_id] = shift
        }
      }
    }

    technicianOptionsRaw.value = (techRes || []).map(t => ({
      ...t,
      is_on_leave: leaveUserIds.has(t.id),
      shift_label: userShiftMap[t.id] ? shiftText(userShiftMap[t.id]) : '未排班',
    }))
  } catch (e) {
    console.error('获取维修员列表失败', e)
  }
}

const handlePicturePreview = () => {}
const handleRemove = () => {}

const handleSubmit = async () => {
  // 清空上次的错误提示
  submitError.value = ''
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const payload = {
      fault_description: form.fault_description,
      technician_id: form.technician_id,
      location: form.location || undefined,
      attachments: form.attachments?.length ? form.attachments : undefined,
      source: 'SUPERVISOR_DISPATCH',
    }
    const res = await request.post('/work-orders/from-dispatch', payload)
    const woId = res?.id || res?.work_order?.id
    ElMessage.success('派工成功，工单已创建')
    // 成功后跳转到工单进度页并高亮新建工单
    router.push(woId ? `/supervisor/progress?highlight=${woId}` : '/supervisor/progress')
  } catch (e) {
    // 失败后留在表单页，顶部显示错误 Alert
    submitError.value = e?.response?.data?.detail || e?.message || '派工提交失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchTechnicians()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); margin: 0; }

.dispatch-wrap {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
.form-card {
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}
.full-width { width: 100%; }

.upload-area {
  display: block;
}
.upload-tip {
  font-size: 12px;
  color: #C9CDD4;
  margin-top: 4px;
}

/* 维修员下拉选项：左右布局 */
.tech-option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 2px 0;
}
.tech-option-left {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tech-option-name {
  font-size: 14px;
  font-weight: 500;
  color: #1D2129;
}
.tech-option-skills {
  font-size: 12px;
  color: #86909C;
}
.tech-option-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.tech-tag-margin {
  margin-left: 4px;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 500;
}
</style>
