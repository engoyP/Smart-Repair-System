<template>
  <div class="tech-detail" v-if="wo">
    <!-- 工单头部 -->
    <div class="detail-header">
      <div class="header-top">
        <span class="wo-no">{{ wo.work_order_no }}</span>
      </div>
      <div class="header-status">{{ statusLabel(wo.status) }}</div>
    </div>

    <!-- 故障信息 -->
    <div class="info-section">
      <h3>故障信息</h3>
      <div class="info-row"><span>设备编码</span><span>{{ wo.device_code || '-' }}</span></div>
      <div class="info-row"><span>故障码</span><span>{{ wo.fault_code || '-' }}</span></div>
      <div class="info-row"><span>故障描述</span><span>{{ wo.fault_description }}</span></div>
      <div class="info-row" v-if="wo.fault_phenomenon"><span>故障现象</span><span>{{ wo.fault_phenomenon }}</span></div>
      <div class="info-row"><span>位置</span><span>{{ wo.location || '-' }}</span></div>
      <div class="info-row"><span>上报时间</span><span>{{ formatTime(wo.created_at) }}</span></div>
    </div>

    <!-- AI 分析结果 -->
    <div class="info-section" v-if="wo.analysis_result">
      <h3>AI 分析</h3>
      <div class="info-row" v-if="wo.confidence != null"><span>置信度</span><span>{{ (wo.confidence * 100).toFixed(0) }}%</span></div>
      <div class="info-row" v-if="wo.root_cause"><span>根因</span><span>{{ wo.root_cause }}</span></div>
      <div class="info-row" v-if="wo.solution_steps"><span>方案建议</span><span>{{ wo.solution_steps }}</span></div>
    </div>

    <!-- 故障图片 -->
    <div class="info-section" v-if="wo.fault_media?.length">
      <h3>现场照片</h3>
      <div class="media-grid">
        <img v-for="(url, i) in wo.fault_media" :key="i" :src="url" class="media-img" />
      </div>
    </div>

    <!-- 库存关联 -->
    <div class="info-section" v-if="inventory?.items?.length">
      <h3>备件库存</h3>
      <div class="stock-item" v-for="sp in inventory.items" :key="sp.id">
        <span class="stock-name">{{ sp.part_name }}</span>
        <span class="stock-qty" :class="{ out: sp.stock_quantity <= 0, low: sp.stock_quantity <= sp.safety_stock }">
          库存 {{ sp.stock_quantity }}
        </span>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar" v-if="['ASSIGNED', 'IN_PROGRESS'].includes(wo.status)">
      <button
        v-if="wo.status === 'ASSIGNED'"
        class="action-btn primary"
        @click="handleStart"
        :disabled="loading"
      >接单开始维修</button>

      <button
        v-if="wo.status === 'IN_PROGRESS'"
        class="action-btn primary"
        @click="showReport = true"
      >提交完成报告</button>
    </div>

    <!-- 已完成工单的报告展示 -->
    <div class="info-section" v-if="wo.completion_report">
      <h3>完成报告</h3>
      <div class="info-row"><span>处理时长</span><span>{{ wo.completion_report.work_hours || 0 }}h</span></div>
      <div class="info-row"><span>处理描述</span><span>{{ wo.completion_report.solution_desc || '-' }}</span></div>
    </div>

    <!-- 完成报告弹窗 -->
    <div class="report-modal" v-if="showReport" @click.self="showReport = false">
      <div class="report-panel">
        <h3>完成报告</h3>

        <label>工时（小时）</label>
        <input v-model.number="reportForm.work_hours" type="number" step="0.5" min="0" class="report-input" />

        <label>处理说明</label>
        <textarea v-model="reportForm.solution_desc" class="report-textarea" rows="3" placeholder="描述处理过程和结果..."></textarea>

        <label>拍照</label>
        <div class="report-photos">
          <div class="add-photo" @click="addPhoto">+</div>
          <img v-for="(url, i) in reportForm.completion_photos" :key="i" :src="url" class="photo-thumb" />
        </div>

        <div class="report-actions">
          <button class="btn-cancel" @click="showReport = false">取消</button>
          <button class="btn-submit" @click="handleComplete" :disabled="completing">
            {{ completing ? '提交中...' : '提交' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../../api'

const route = useRoute()
const router = useRouter()
const wo = ref(null)
const inventory = ref(null)
const loading = ref(false)
const completing = ref(false)
const showReport = ref(false)

const reportForm = ref({ work_hours: 1.0, solution_desc: '', completion_photos: [] })


const statusLabel = (s) => ({ ASSIGNED: '待接单', IN_PROGRESS: '维修中', COMPLETED: '已完成', APPROVED: '已审批' }[s] || s)
const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : '-'

const fetchData = async () => {
  try {
    const res = await request.get(`/dingtalk/tech/detail/${route.params.id}`)
    wo.value = res
    inventory.value = res.inventory
  } catch { /* handled */ }
}

const handleStart = async () => {
  loading.value = true
  try {
    await request.post(`/dingtalk/tech/start/${route.params.id}`)
    ElMessage.success('已开始维修')
    await fetchData()
  } catch { /* handled */ }
  finally { loading.value = false }
}

const addPhoto = () => {
  reportForm.value.completion_photos.push(
    `https://via.placeholder.com/120/52C41A/fff?text=Done_${Date.now()}`
  )
}

const handleComplete = async () => {
  completing.value = true
  try {
    await request.post(`/dingtalk/tech/complete/${route.params.id}`, {
      work_hours: reportForm.value.work_hours,
      solution_desc: reportForm.value.solution_desc,
      completion_photos: reportForm.value.completion_photos,
    })
    ElMessage.success('完成报告已提交')
    showReport.value = false
    router.push('/m/queue')
  } catch { /* handled */ }
  finally { completing.value = false }
}

onMounted(fetchData)
</script>

<style scoped>
.tech-detail { padding: 16px; padding-bottom: 80px; }

.detail-header {
  background: linear-gradient(135deg, #1677FF, #4096FF);
  border-radius: 12px; padding: 18px; color: #fff; margin-bottom: 16px;
}
.header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.wo-no { font-size: 18px; font-weight: 600; font-family: monospace; }
.header-status { font-size: 14px; opacity: 0.9; }

.info-section {
  background: #fff; border-radius: 10px; padding: 14px; margin-bottom: 12px;
}
.info-section h3 { font-size: 15px; font-weight: 600; color: #1D2129; margin-bottom: 10px; }
.info-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #F5F6F8; font-size: 13px; }
.info-row:last-child { border-bottom: none; }
.info-row span:first-child { color: #86909C; min-width: 60px; }
.info-row span:last-child { color: #1D2129; text-align: right; flex: 1; margin-left: 12px; }

.media-grid { display: flex; gap: 8px; overflow-x: auto; }
.media-img { width: 100px; height: 75px; border-radius: 6px; object-fit: cover; flex-shrink: 0; }

.stock-item { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; }
.stock-qty { color: #00B42A; font-weight: 500; }
.stock-qty.low { color: #FF7D00; }
.stock-qty.out { color: #F53F3F; }

.action-bar { position: fixed; bottom: 0; left: 0; right: 0; padding: 12px 16px; background: #fff; box-shadow: 0 -2px 8px rgba(0,0,0,.06); max-width: 430px; margin: 0 auto; }
.action-btn {
  width: 100%; padding: 14px; border: none; border-radius: 8px;
  font-size: 16px; font-weight: 500; cursor: pointer;
}
.action-btn.primary { background: #1677FF; color: #fff; }
.action-btn:disabled { opacity: 0.5; }

/* 报告弹窗 */
.report-modal {
  position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 200;
  display: flex; align-items: flex-end; justify-content: center;
}
.report-panel {
  background: #fff; border-radius: 16px 16px 0 0; padding: 20px;
  width: 100%; max-width: 430px; max-height: 80vh; overflow-y: auto;
}
.report-panel h3 { font-size: 18px; margin-bottom: 16px; text-align: center; }
.report-panel label { display: block; font-size: 14px; color: #4E5969; margin: 12px 0 6px; }
.report-input {
  width: 100%; padding: 10px; border: 1px solid #D9D9D9; border-radius: 8px; font-size: 14px; box-sizing: border-box;
}
.report-textarea {
  width: 100%; padding: 10px; border: 1px solid #D9D9D9; border-radius: 8px; font-size: 14px; box-sizing: border-box; resize: vertical;
}
.report-photos { display: flex; gap: 8px; flex-wrap: wrap; }
.add-photo {
  width: 60px; height: 60px; border: 1px dashed #D9D9D9; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; color: #C9CDD4; cursor: pointer;
}
.photo-thumb { width: 60px; height: 60px; border-radius: 8px; object-fit: cover; }
.report-actions { display: flex; gap: 12px; margin-top: 20px; }
.btn-cancel, .btn-submit {
  flex: 1; padding: 12px; border-radius: 8px; font-size: 15px; border: none; cursor: pointer;
}
.btn-cancel { background: #F2F3F5; color: #4E5969; }
.btn-submit { background: #1677FF; color: #fff; }
.btn-submit:disabled { opacity: 0.5; }
</style>
