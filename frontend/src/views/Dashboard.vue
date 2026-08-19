<template>
  <div class="dashboard">
    <div class="page-header">
      <h2 class="page-title">数据驾驶舱</h2>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-cards">
      <el-card class="stat-card" shadow="never" @click="$router.push('/work-orders')">
        <div class="stat-body">
          <div class="stat-icon-box primary">
            <el-icon :size="24"><Document /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.total_orders }}</div>
            <div class="stat-label">总工单数</div>
            <div class="stat-extra">今日新增 <strong>{{ stats.today_orders }}</strong></div>
          </div>
        </div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="$router.push('/work-orders')">
        <div class="stat-body">
          <div class="stat-icon-box warning">
            <el-icon :size="24"><WarningFilled /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value warning">{{ stats.pending_review }}</div>
            <div class="stat-label">草稿工单</div>
            <div class="stat-extra">需要处理</div>
          </div>
        </div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="$router.push('/knowledge')">
        <div class="stat-body">
          <div class="stat-icon-box success">
            <el-icon :size="24"><Reading /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ knowledgeContentTotal }}</div>
            <div class="stat-label">知识库内容</div>
            <div class="stat-extra">知识 {{ stats.total_knowledge }} · 手册 {{ stats.total_manual_codes }}</div>
          </div>
        </div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="$router.push('/spare-parts')">
        <div class="stat-body">
          <div class="stat-icon-box" :class="stats.stock_alert > 0 ? 'danger' : 'info'">
            <el-icon :size="24"><Box /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value" :class="stats.stock_alert > 0 ? 'danger' : ''">{{ stats.stock_alert }}</div>
            <div class="stat-label">库存预警</div>
            <div class="stat-extra">{{ stats.stock_alert > 0 ? `${stats.stock_alert} 项需补货` : '库存正常' }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 设备监控行 -->
    <div class="section-block">
      <div class="section-block-header">
        <span class="section-block-title">设备监控概览</span>
        <el-button size="small" text type="primary" @click="$router.push('/devices')">进入监控面板 →</el-button>
      </div>
      <div class="monitor-cards">
        <el-card class="mon-card shadow-none" @click="$router.push('/devices')">
          <div class="mon-card-body">
            <div class="mon-num" style="color:#2563EB">{{ stats.total_devices }}</div>
            <div class="mon-lbl">设备总数</div>
          </div>
        </el-card>
        <el-card class="mon-card shadow-none mon-online" @click="$router.push('/devices?status=ONLINE')">
          <div class="mon-card-body">
            <div class="mon-dot" style="background:#10B981"></div>
            <div class="mon-num" style="color:#059669">{{ dm.online }}</div>
            <div class="mon-lbl">正常运行</div>
          </div>
        </el-card>
        <el-card class="mon-card shadow-none mon-alarm" @click="$router.push('/devices?status=ALARM')">
          <div class="mon-card-body">
            <div class="mon-dot" style="background:#F59E0B"></div>
            <div class="mon-num" style="color:#D97706">{{ dm.alarm }}</div>
            <div class="mon-lbl">告警中</div>
          </div>
        </el-card>
        <el-card class="mon-card shadow-none mon-fault" @click="$router.push('/devices?status=FAULT')">
          <div class="mon-card-body">
            <div class="mon-dot" style="background:#EF4444"></div>
            <div class="mon-num" style="color:#DC2626">{{ dm.fault }}</div>
            <div class="mon-lbl">故障停机</div>
          </div>
        </el-card>
        <el-card class="mon-card shadow-none mon-offline" @click="$router.push('/devices?status=OFFLINE')">
          <div class="mon-card-body">
            <div class="mon-dot" style="background:#6B7280"></div>
            <div class="mon-num" style="color:#6B7280">{{ dm.offline }}</div>
            <div class="mon-lbl">离线</div>
          </div>
        </el-card>
        <el-card class="mon-card shadow-none mon-alarm" @click="$router.push('/devices?has_fault=true')">
          <div class="mon-card-body">
            <div class="mon-dot" style="background:#7C3AED"></div>
            <div class="mon-num" style="color:#7C3AED">{{ dm.with_fault_tags }}</div>
            <div class="mon-lbl">故障标签数</div>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 双栏布局 -->
    <div class="dashboard-grid">
      <!-- 最近工单 -->
      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-header">
            <span class="section-title">最近工单</span>
            <el-button size="small" text type="primary" @click="$router.push('/work-orders')">查看全部</el-button>
          </div>
        </template>
        <el-table :data="recentOrders" stripe size="small">
          <el-table-column prop="work_order_no" label="工单编号" width="160" />
          <el-table-column prop="fault_description" label="故障描述" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <span class="status-tag" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="75">
            <template #default="{ row }">
              <span v-if="row.confidence != null" style="font-size:12px;font-weight:600"
                :style="{ color: row.confidence >= 0.8 ? '#00B42A' : '#86909C' }">
                {{ (row.confidence * 100).toFixed(0) }}%
              </span>
              <span v-else style="color:#C9CDD4;font-size:12px">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="140">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 库存预警 -->
      <el-card class="section-card" shadow="never">
        <template #header>
          <div class="section-header">
            <span class="section-title">库存预警</span>
            <el-button size="small" text type="primary" @click="$router.push('/spare-parts')">查看全部</el-button>
          </div>
        </template>
        <div v-if="alertItems.length === 0" style="text-align: center; padding: 40px 0; color: #86909C">
          库存正常，暂无预警
        </div>
        <div v-else class="alert-list">
          <div v-for="item in alertItems.slice(0, 8)" :key="item.id" class="alert-item">
            <div class="alert-info">
              <span class="alert-code">{{ item.part_code }}</span>
              <span class="alert-name">{{ item.part_name }}</span>
            </div>
            <div class="alert-quantity">
              <span class="qty-current" :class="{ 'qty-out': item.stock_quantity <= 0 }">
                库存 {{ item.stock_quantity }}
              </span>
              <span class="qty-safe">安全 {{ item.safety_stock }}</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 知识统计 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="section-header">
            <span class="section-title">知识库与手册概览</span>
          <el-button size="small" text type="primary" @click="$router.push('/knowledge/list')">知识管理</el-button>
        </div>
      </template>
      <div class="knowledge-stats">
        <div class="ks-item">
          <div class="ks-value">{{ knowledgeContentTotal }}</div>
          <div class="ks-label">内容总数</div>
        </div>
        <div class="ks-item">
          <div class="ks-value">{{ stats.total_knowledge }}</div>
          <div class="ks-label">知识条目</div>
        </div>
        <div class="ks-item">
          <div class="ks-value" style="color: #FF7D00">{{ stats.under_review_knowledge }}</div>
          <div class="ks-label">审核中</div>
        </div>
        <div class="ks-item">
          <div class="ks-value" style="color: #00B42A">{{ stats.published_knowledge }}</div>
          <div class="ks-label">已发布</div>
        </div>
        <div class="ks-item clickable" @click="$router.push('/knowledge/manuals')">
          <div class="ks-value">{{ stats.total_manual_codes }}</div>
          <div class="ks-label">设备手册</div>
        </div>
        <div class="ks-item">
          <div class="ks-value">{{ stats.total_devices }}</div>
          <div class="ks-label">设备台账</div>
        </div>
        <div class="ks-item">
          <div class="ks-value">{{ stats.total_spare_parts }}</div>
          <div class="ks-label">备件品类</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import request from '../api'
import dayjs from 'dayjs'

const stats = ref({
  total_orders: 0,
  today_orders: 0,
  pending_review: 0,
  total_knowledge: 0,
  total_manual_codes: 0,
  published_knowledge: 0,
  under_review_knowledge: 0,
  stock_alert: 0,
  total_devices: 0,
  total_spare_parts: 0,
  device_monitor: { online: 0, offline: 0, alarm: 0, fault: 0, unknown: 0, with_fault_tags: 0 },
})
const dm = computed(() => stats.value.device_monitor)
const recentOrders = ref([])
const alertItems = ref([])

const knowledgeContentTotal = computed(() => {
  return (stats.value.total_knowledge || 0) + (stats.value.total_manual_codes || 0)
})

const statusMap = {
  DRAFT: '草稿',
  IN_PROGRESS: '维修中',
  COMPLETED: '已完成',
}
const statusLabel = (s) => statusMap[s] || s
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const fetchStats = async () => {
  try {
    const res = await request.get('/dashboard/stats')

    stats.value.total_orders = res.total_orders || 0
    stats.value.total_knowledge = res.total_knowledge || 0
    stats.value.total_manual_codes = res.total_manual_codes || 0
    stats.value.total_devices = res.total_devices || 0
    stats.value.total_spare_parts = res.total_spare_parts || 0
    stats.value.stock_alert = res.stock_alert || 0
    stats.value.pending_review = res.pending_review || 0
    stats.value.today_orders = res.today_orders || 0
    stats.value.published_knowledge = res.published_knowledge || 0
    stats.value.under_review_knowledge = res.under_review_knowledge || 0
    stats.value.device_monitor = res.device_monitor || stats.value.device_monitor

    // 最近工单
    recentOrders.value = res.recent_orders || []

    // 预警备件列表
    alertItems.value = []
    if (res.out_of_stock_items?.length) {
      alertItems.value.push(...res.out_of_stock_items)
    }
    if (res.low_stock_items?.length) {
      alertItems.value.push(...res.low_stock_items)
    }
  } catch { /* handled */ }
}

const fetchRecentOrders = async () => {} // 已合并到 fetchStats

onMounted(() => { fetchStats() })
</script>

<style scoped>
.page-header { margin-bottom: 24px; }

.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.stat-card { cursor: pointer; }
.stat-card:hover { box-shadow: var(--shadow-card-hover); }

.stat-body { display: flex; align-items: center; gap: 16px; }
.stat-icon-box {
  width: 52px; height: 52px;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.stat-icon-box.primary { background: var(--el-color-primary-light-9); color: var(--color-primary); }
.stat-icon-box.warning { background: #FFF3E8; color: var(--color-warning); }
.stat-icon-box.success { background: #E8F8EE; color: var(--color-success); }
.stat-icon-box.danger { background: #FFECEC; color: var(--color-danger); }
.stat-icon-box.info { background: #E8F3FF; color: var(--color-info); }

.stat-info { flex: 1; min-width: 0; }
.stat-value { font-size: 28px; font-weight: 700; color: var(--color-text-primary); line-height: 1.1; }
.stat-value.warning { color: var(--color-warning); }
.stat-value.danger { color: var(--color-danger); }
.stat-label { font-size: 14px; color: var(--color-text-secondary); margin-top: 4px; }
.stat-extra { font-size: 12px; color: var(--color-text-tertiary); margin-top: 6px; }
.stat-extra strong { color: var(--color-text-primary); }

.dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }

.section-card { margin-bottom: 24px; }
.section-header { display: flex; justify-content: space-between; align-items: center; }
.section-title { font-size: 16px; font-weight: 600; color: var(--color-text-primary); }

/* 预警列表 */
.alert-list { max-height: 280px; overflow-y: auto; }
.alert-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--color-border-light);
}
.alert-item:last-child { border-bottom: none; }
.alert-info { display: flex; gap: 8px; align-items: center; min-width: 0; }
.alert-code { font-size: 12px; color: var(--color-text-secondary); font-family: monospace; white-space: nowrap; }
.alert-name { font-size: 13px; color: var(--color-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.alert-quantity { display: flex; gap: 12px; font-size: 13px; flex-shrink: 0; }
.qty-current { color: var(--color-warning); font-weight: 600; }
.qty-current.qty-out { color: var(--color-danger); }
.qty-safe { color: var(--color-text-disabled); }

/* 知识统计 */
.knowledge-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 12px;
}
.ks-item {
  text-align: center;
  min-width: 0;
  padding: 12px 8px;
  background: #FAFBFC;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
}
.ks-item.clickable { cursor: pointer; transition: border-color .2s, box-shadow .2s; }
.ks-item.clickable:hover { border-color: rgba(15, 198, 194, 0.45); box-shadow: var(--shadow-card-hover); }
.ks-value { font-size: 24px; font-weight: 700; color: var(--color-text-primary); }
.ks-label { font-size: 13px; color: var(--color-text-tertiary); margin-top: 6px; }

/* 设备监控行 */
.section-block { margin-bottom: 24px; background: transparent; }
.section-block-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-block-title { font-size: 16px; font-weight: 600; color: var(--color-text-primary); }
.monitor-cards { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; }
.mon-card { border-radius: 10px; border: 1px solid var(--color-border-light); cursor: pointer; transition: all .2s; }
.mon-card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,0,0,.06); }
.mon-card :deep(.el-card__body) { padding: 14px 16px; }
.mon-card-body { display: flex; flex-direction: column; gap: 2px; position: relative; }
.mon-num { font-size: 24px; font-weight: 700; line-height: 1.2; }
.mon-lbl { font-size: 12px; color: #6B7280; margin-top: 2px; }
.mon-sub { font-size: 11px; color: #9CA3AF; margin-top: 6px; }
.mon-dot { position: absolute; top: 2px; right: 2px; width: 8px; height: 8px; border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .45 } }
.mon-online { border-left: 3px solid #10B981; }
.mon-alarm { border-left: 3px solid #F59E0B; }
.mon-fault { border-left: 3px solid #EF4444; }
.mon-offline { border-left: 3px solid #9CA3AF; }

@media (max-width: 900px) {
  .monitor-cards { grid-template-columns: repeat(3, 1fr); }
  .knowledge-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 600px) {
  .knowledge-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
