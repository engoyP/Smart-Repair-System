<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" circle @click="$router.back()" />
        <h2 class="page-title">实时进度看板</h2>
        <span class="update-tip" :class="{ 'pulse': loading }">
          <span class="dot"></span>
          {{ loading ? '刷新中...' : `上次更新 ${lastUpdateTime}` }}
        </span>
      </div>
      <div class="header-actions">
        <el-switch
          v-model="autoRefresh"
          active-text="自动刷新"
          inactive-text="手动"
          inline-prompt
          @change="toggleAutoRefresh"
        />
      </div>
    </div>

    <!-- 4 张统计卡，点击滚动到对应列 -->
    <div class="stats-row">
      <el-card class="stat-card stat-submitted" shadow="hover" @click="scrollToCol('submitted')">
        <div class="stat-icon">
          <el-icon :size="28"><DocumentAdd /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-num">{{ stats.submitted }}</div>
          <div class="stat-label">待派工</div>
        </div>
      </el-card>

      <el-card class="stat-card stat-assigned" shadow="hover" @click="scrollToCol('assigned')">
        <div class="stat-icon">
          <el-icon :size="28"><User /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-num">{{ stats.assigned }}</div>
          <div class="stat-label">待接受</div>
        </div>
      </el-card>

      <el-card class="stat-card stat-progress" shadow="hover" @click="scrollToCol('in_progress')">
        <div class="stat-icon">
          <el-icon :size="28"><Loading /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-num">{{ stats.in_progress }}</div>
          <div class="stat-label">进行中</div>
        </div>
      </el-card>

      <el-card class="stat-card stat-completed" shadow="hover" @click="scrollToCol('completed')">
        <div class="stat-icon">
          <el-icon :size="28"><CircleCheck /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-num">{{ stats.completed_today }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </el-card>
    </div>

    <!-- 4 列看板，flex 布局，等宽可横向滚动 -->
    <div class="board-cols">
      <!-- ① 待派工 -->
      <div class="col col-submitted" ref="colSubmitted">
        <div class="col-header">
          <h3 class="col-title">
            <span class="col-indicator indicator-submitted"></span>
            待派工 ({{ boardData.submitted.length }})
          </h3>
        </div>
        <div class="col-body" v-loading="loading">
          <div v-if="boardData.submitted.length === 0" class="col-empty">
            <el-icon :size="32" color="#C9CDD4"><DocumentAdd /></el-icon>
            <span>暂无待派工工单</span>
          </div>
          <el-card
            v-for="wo in boardData.submitted"
            :key="wo.id"
            class="wo-card col-submitted"
            :class="{ 'highlight-flash': highlightId === wo.id, 'is-overtime': wo.is_overtime }"
            shadow="hover"
            @click="goDetail(wo)"
          >
            <div class="overtime-badge" v-if="wo.is_overtime">
              <el-icon><Warning /></el-icon> 超时未接受
            </div>
            <div class="wo-card-header">
              <span class="wo-no">{{ wo.work_order_no }}</span>
            </div>
            <div class="wo-fault">{{ wo.fault_description }}</div>
            <div class="wo-meta">
              <span class="wo-tech">
                <el-icon><User /></el-icon>
                {{ wo.technician_name || '未指派' }}
              </span>
              <span class="wo-time">{{ formatTime(wo.created_at) }}</span>
            </div>
            <div class="timeline-dots">
              <div
                v-for="step in getTimelineState(wo)"
                :key="step.key"
                class="tl-step"
                :class="{ 'tl-done': step.done && !step.isCurrent, 'tl-current': step.isCurrent, 'tl-pending': !step.done }"
              >
                <span class="tl-dot"></span>
                <span class="tl-label">{{ step.label }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- ② 待接受 -->
      <div class="col col-assigned" ref="colAssigned">
        <div class="col-header">
          <h3 class="col-title">
            <span class="col-indicator indicator-assigned"></span>
            待接受 ({{ boardData.assigned.length }})
          </h3>
        </div>
        <div class="col-body" v-loading="loading">
          <div v-if="boardData.assigned.length === 0" class="col-empty">
            <el-icon :size="32" color="#C9CDD4"><User /></el-icon>
            <span>暂无待接受工单</span>
          </div>
          <el-card
            v-for="wo in boardData.assigned"
            :key="wo.id"
            class="wo-card col-assigned"
            :class="{ 'highlight-flash': highlightId === wo.id, 'is-overtime': wo.is_overtime }"
            shadow="hover"
            @click="goDetail(wo)"
          >
            <div class="overtime-badge" v-if="wo.is_overtime">
              <el-icon><Warning /></el-icon> 超时未接受
            </div>
            <div class="wo-card-header">
              <span class="wo-no">{{ wo.work_order_no }}</span>
            </div>
            <div class="wo-fault">{{ wo.fault_description }}</div>
            <div class="wo-meta">
              <span class="wo-tech">
                <el-icon><User /></el-icon>
                {{ wo.technician_name || '未指派' }}
              </span>
              <span class="wo-time">{{ formatTime(wo.created_at) }}</span>
            </div>
            <div class="timeline-dots">
              <div
                v-for="step in getTimelineState(wo)"
                :key="step.key"
                class="tl-step"
                :class="{ 'tl-done': step.done && !step.isCurrent, 'tl-current': step.isCurrent, 'tl-pending': !step.done }"
              >
                <span class="tl-dot"></span>
                <span class="tl-label">{{ step.label }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- ③ 进行中 -->
      <div class="col col-in-progress" ref="colInProgress">
        <div class="col-header">
          <h3 class="col-title">
            <span class="col-indicator indicator-in-progress"></span>
            进行中 ({{ boardData.in_progress.length }})
          </h3>
        </div>
        <div class="col-body" v-loading="loading">
          <div v-if="boardData.in_progress.length === 0" class="col-empty">
            <el-icon :size="32" color="#C9CDD4"><Loading /></el-icon>
            <span>暂无进行中工单</span>
          </div>
          <el-card
            v-for="wo in boardData.in_progress"
            :key="wo.id"
            class="wo-card col-in-progress"
            :class="{ 'highlight-flash': highlightId === wo.id, 'is-overtime': wo.is_overtime }"
            shadow="hover"
            @click="goDetail(wo)"
          >
            <div class="overtime-badge" v-if="wo.is_overtime">
              <el-icon><Warning /></el-icon> 超时未接受
            </div>
            <div class="wo-card-header">
              <span class="wo-no">{{ wo.work_order_no }}</span>
            </div>
            <div class="wo-fault">{{ wo.fault_description }}</div>
            <div class="wo-meta">
              <span class="wo-tech">
                <el-icon><User /></el-icon>
                {{ wo.technician_name || '未指派' }}
              </span>
              <span class="wo-time">{{ formatTime(wo.created_at) }}</span>
            </div>
            <div class="timeline-dots">
              <div
                v-for="step in getTimelineState(wo)"
                :key="step.key"
                class="tl-step"
                :class="{ 'tl-done': step.done && !step.isCurrent, 'tl-current': step.isCurrent, 'tl-pending': !step.done }"
              >
                <span class="tl-dot"></span>
                <span class="tl-label">{{ step.label }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- ④ 已完成 -->
      <div class="col col-completed" ref="colCompleted">
        <div class="col-header">
          <h3 class="col-title">
            <span class="col-indicator indicator-completed"></span>
            已完成 ({{ boardData.completed.length }})
          </h3>
        </div>
        <div class="col-body" v-loading="loading">
          <div v-if="boardData.completed.length === 0" class="col-empty">
            <el-icon :size="32" color="#C9CDD4"><CircleCheck /></el-icon>
            <span>暂无已完成工单</span>
          </div>
          <el-card
            v-for="wo in boardData.completed"
            :key="wo.id"
            class="wo-card col-completed"
            :class="{ 'highlight-flash': highlightId === wo.id, 'is-overtime': wo.is_overtime }"
            shadow="hover"
            @click="goDetail(wo)"
          >
            <div class="overtime-badge" v-if="wo.is_overtime">
              <el-icon><Warning /></el-icon> 超时未接受
            </div>
            <div class="wo-card-header">
              <span class="wo-no">{{ wo.work_order_no }}</span>
            </div>
            <div class="wo-fault">{{ wo.fault_description }}</div>
            <div class="wo-meta">
              <span class="wo-tech">
                <el-icon><User /></el-icon>
                {{ wo.technician_name || '未指派' }}
              </span>
              <span class="wo-time">{{ formatTime(wo.created_at) }}</span>
            </div>
            <div class="timeline-dots">
              <div
                v-for="step in getTimelineState(wo)"
                :key="step.key"
                class="tl-step"
                :class="{ 'tl-done': step.done && !step.isCurrent, 'tl-current': step.isCurrent, 'tl-pending': !step.done }"
              >
                <span class="tl-dot"></span>
                <span class="tl-label">{{ step.label }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, DocumentAdd, User, Loading, CircleCheck, Warning
} from '@element-plus/icons-vue'
import request from '../api'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const autoRefresh = ref(true)
const lastUpdateTime = ref('--:--:--')
// 新工单高亮 ID（URL ?highlight=工单ID 触发，3秒后清除）
const highlightId = ref(null)

// 4 列 ref，供统计卡点击滚动定位
const colSubmitted = ref(null)
const colAssigned = ref(null)
const colInProgress = ref(null)
const colCompleted = ref(null)

// 看板数据（4 列 + stats）
const boardData = ref({
  submitted: [],
  assigned: [],
  in_progress: [],
  completed: [],
  stats: { submitted: 0, assigned: 0, in_progress: 0, completed_today: 0 }
})

// 统计卡数据
const stats = ref({
  submitted: 0,
  assigned: 0,
  in_progress: 0,
  completed_today: 0,
})

// 进度时间轴步骤：派工→接受→到达→检查→维修→完成
const TIMELINE_STEPS = [
  { key: 'ASSIGNED', label: '派工' },
  { key: 'ACCEPTED', label: '接受' },
  { key: 'ARRIVED', label: '到达' },
  { key: 'INSPECTING', label: '检查' },
  { key: 'IN_PROGRESS', label: '维修' },
  { key: 'COMPLETED', label: '完成' },
]


const formatTime = (t) => t ? dayjs(t).format('MM-DD HH:mm') : '-'

// 计算工单时间轴每一步的状态：已完成 / 当前 / 未完成
const getTimelineState = (wo) => {
  const timeline = wo.progress_timeline || []
  // 构建 status -> 日志项 映射（后端字段为 status / timestamp）
  const map = {}
  timeline.forEach(item => {
    const key = item.status || item.step || item.key || item.to_status
    if (key) map[key] = item
  })
  const currentStatus = wo.status
  return TIMELINE_STEPS.map(s => {
    const info = map[s.key]
    const done = !!info
    const isCurrent = s.key === currentStatus
    return {
      key: s.key,
      label: s.label,
      done,
      isCurrent,
      time: info?.timestamp || info?.time || info?.created_at || ''
    }
  })
}

// 统计卡点击 → 滚动到对应列
const scrollToCol = (colName) => {
  const refs = {
    submitted: colSubmitted,
    assigned: colAssigned,
    in_progress: colInProgress,
    completed: colCompleted
  }
  refs[colName]?.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 卡片点击 → 跳转工单详情
const goDetail = (wo) => router.push('/work-orders/' + wo.id)

// 获取看板数据
const fetchBoardData = async () => {
  loading.value = true
  try {
    const res = await request.get('/work-orders/progress-board')
    boardData.value = res
    // 更新统计卡
    stats.value = res.stats
  } catch (e) {
    console.error('获取看板数据失败', e)
  } finally {
    loading.value = false
    lastUpdateTime.value = new Date().toLocaleTimeString()
  }
}

// 自动刷新：每 15 秒一次
let timer = null
const toggleAutoRefresh = (v) => {
  if (v) {
    if (!timer) timer = setInterval(fetchBoardData, 15000)
  } else {
    if (timer) { clearInterval(timer); timer = null }
  }
}

onMounted(() => {
  fetchBoardData()
  if (autoRefresh.value) timer = setInterval(fetchBoardData, 15000)
  // URL 带 highlight 参数时，对应卡片边框闪烁 3 秒
  if (route.query.highlight) {
    highlightId.value = parseInt(route.query.highlight)
    setTimeout(() => { highlightId.value = null }, 3000)
  }
})

onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
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
  gap: 14px;
}
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); margin: 0; }

.update-tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #86909C;
}
.update-tip .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #00B42A;
}
.update-tip.pulse .dot {
  background: #3491FA;
  animation: pulse 1s infinite;
}
@keyframes pulse {
  0%,100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* 统计卡 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  cursor: pointer;
  border: none;
  overflow: hidden;
  position: relative;
  color: #fff;
  transition: transform .2s;
}
.stat-card:hover { transform: translateY(-2px); }
.stat-card :deep(.el-card__body) {
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.stat-submitted { background: linear-gradient(135deg, #86909C 0%, #A0A8B3 100%); }
.stat-assigned { background: linear-gradient(135deg, #FF7D00 0%, #FF9A2E 100%); }
.stat-progress { background: linear-gradient(135deg, #3491FA 0%, #5CADFF 100%); }
.stat-completed { background: linear-gradient(135deg, #00B42A 0%, #36CFC9 100%); }
.stat-icon {
  width: 52px; height: 52px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,.18);
  border-radius: 12px;
  flex-shrink: 0;
}
.stat-content { color: #fff; }
.stat-num {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  margin-bottom: 4px;
}
.stat-label {
  font-size: 13px;
  opacity: 0.9;
}

/* 4 列看板：flex 布局，等宽，可横向滚动 */
.board-cols {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  overflow-x: auto;
  padding-bottom: 8px;
}
.col {
  flex: 1 1 0;
  min-width: 280px;
  background: #fff;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 300px);
}
.col-header {
  padding: 14px 16px;
  border-bottom: 1px solid #F2F3F5;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.col-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
  display: flex;
  align-items: center;
  gap: 8px;
}
.col-indicator {
  width: 8px; height: 8px; border-radius: 50%;
}
.indicator-submitted { background: #86909C; }
.indicator-assigned { background: #FF7D00; }
.indicator-in-progress { background: #3491FA; }
.indicator-completed { background: #00B42A; }

.col-body {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
}

.col-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  color: #C9CDD4;
  font-size: 13px;
}

/* 工单卡片 */
.wo-card {
  position: relative;
  margin-bottom: 10px;
  cursor: pointer;
  border: 1px solid #F2F3F5;
  overflow: hidden;
  transition: all .2s;
}
.wo-card:hover {
  border-color: #3491FA;
  box-shadow: 0 2px 8px rgba(52, 145, 250, 0.12);
}
.wo-card :deep(.el-card__body) {
  padding: 12px 14px;
}
/* 卡片左侧色带：按列着色 */
.wo-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--col-color, #86909C);
  z-index: 1;
}
.wo-card.col-submitted { --col-color: #86909C; }
.wo-card.col-assigned { --col-color: #FF7D00; }
.wo-card.col-in-progress { --col-color: #3491FA; }
.wo-card.col-completed { --col-color: #00B42A; }

/* 超时标记：左侧红色色带 + 闪烁 */
.wo-card.is-overtime::before {
  background: #F53F3F;
  animation: overtime-strip 1s infinite;
}
@keyframes overtime-strip {
  0%, 100% { background: #F53F3F; }
  50% { background: #FFB3B3; }
}

/* 新工单高亮：边框闪烁 3 秒（0.5s × 6 次） */
.wo-card.highlight-flash {
  animation: highlight-flash 0.5s 6;
  z-index: 5;
}
@keyframes highlight-flash {
  0%, 100% {
    border-color: #3491FA;
    box-shadow: 0 0 0 3px rgba(52, 145, 250, 0.5), 0 2px 8px rgba(52, 145, 250, 0.3);
  }
  50% {
    border-color: #FF7D00;
    box-shadow: 0 0 0 3px rgba(255, 125, 0, 0.6), 0 2px 12px rgba(255, 125, 0, 0.4);
  }
}

/* 超时徽标 */
.overtime-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: #F53F3F;
  background: #FFECEC;
  padding: 2px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
  font-weight: 600;
}

.wo-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.wo-no {
  font-size: 13px;
  font-weight: 600;
  color: #1D2129;
  font-family: monospace;
}

.wo-fault {
  font-size: 13px;
  color: #4E5969;
  line-height: 1.4;
  margin-bottom: 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wo-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #86909C;
}
.wo-tech {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: #4E5969;
}
.wo-tech .el-icon { font-size: 12px; }
.wo-time {
  font-size: 11px;
  color: #C9CDD4;
}

/* 进度时间轴：纯 CSS 圆点 */
.timeline-dots {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 10px 2px 0;
  margin-top: 8px;
  border-top: 1px dashed #F2F3F5;
}
.tl-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
}
.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid #C9CDD4;
  background: #fff;
  transition: all .2s;
}
/* 已完成步骤：实心蓝 */
.tl-done .tl-dot {
  background: #3491FA;
  border-color: #3491FA;
}
.tl-done .tl-label {
  color: #3491FA;
}
/* 当前步骤：放大 + 脉冲动画 */
.tl-current .tl-dot {
  width: 14px;
  height: 14px;
  background: #3491FA;
  border-color: #3491FA;
  animation: dot-pulse 1.2s infinite;
}
.tl-current .tl-label {
  color: #3491FA;
  font-weight: 600;
}
/* 未完成步骤：空心灰 */
.tl-pending .tl-dot {
  background: #fff;
  border-color: #C9CDD4;
}
.tl-pending .tl-label {
  color: #C9CDD4;
}
.tl-label {
  font-size: 10px;
  color: #86909C;
  white-space: nowrap;
}
@keyframes dot-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(52, 145, 250, 0.6); }
  50% { box-shadow: 0 0 0 5px rgba(52, 145, 250, 0); }
}

@media (max-width: 1200px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .col { max-height: 500px; }
}
</style>
