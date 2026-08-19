<template>
  <div class="tech-queue">
    <!-- 状态切换 -->
    <div class="status-bar">
      <span
        v-for="tab in tabs"
        :key="tab.key"
        class="status-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key; fetchData()"
      >{{ tab.label }} ({{ tab.count }})</span>
    </div>

    <!-- 工单列表 -->
    <div class="order-list" v-if="list.length">
      <div
        v-for="wo in list"
        :key="wo.id"
        class="order-card"
        @click="$router.push(`/m/detail/${wo.id}`)"
      >
        <div class="card-header">
          <span class="card-no">{{ wo.work_order_no }}</span>
        </div>
        <div class="card-body">{{ wo.fault_description }}</div>
        <div class="card-footer">
          <span class="card-device" v-if="wo.device_code">{{ wo.device_code }}</span>
          <span class="card-location" v-if="wo.location">{{ wo.location }}</span>
          <span class="card-status">{{ statusLabel(wo.status) }}</span>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">+</div>
      <div class="empty-text">暂无工单</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '../../api'

const activeTab = ref('pending')
const tabs = ref([
  { key: 'pending', label: '待处理', count: 0 },
  { key: 'inprogress', label: '进行中', count: 0 },
  { key: 'completed', label: '已完成', count: 0 },
])
const list = ref([])

const statusLabel = (s) => ({ ASSIGNED: '待接单', IN_PROGRESS: '维修中', COMPLETED: '已完成' }[s] || s)

const fetchData = async () => {
  try {
    const res = await request.get('/dingtalk/tech/queue', {
      params: { userid: 'demo_user', page_size: 50 }
    })
    list.value = (res.items || []).filter(wo => {
      if (activeTab.value === 'pending') return wo.status === 'ASSIGNED'
      if (activeTab.value === 'inprogress') return wo.status === 'IN_PROGRESS'
      if (activeTab.value === 'completed') return wo.status === 'COMPLETED'
      return true
    })
    tabs.value[0].count = (res.items || []).filter(w => w.status === 'ASSIGNED').length
    tabs.value[1].count = (res.items || []).filter(w => w.status === 'IN_PROGRESS').length
    tabs.value[2].count = (res.items || []).filter(w => w.status === 'COMPLETED').length
  } catch { /* handled */ }
}

onMounted(fetchData)
</script>

<style scoped>
.tech-queue { padding: 16px; }

.status-bar { display: flex; margin-bottom: 16px; background: #fff; border-radius: 8px; overflow: hidden; }
.status-tab {
  flex: 1; text-align: center; padding: 12px 0; font-size: 14px;
  color: #86909C; cursor: pointer; border-bottom: 2px solid transparent;
}
.status-tab.active { color: #1677FF; border-bottom-color: #1677FF; font-weight: 500; }

.order-list { display: flex; flex-direction: column; gap: 12px; }
.order-card {
  background: #fff; border-radius: 10px; padding: 14px; cursor: pointer;
  border-left: 3px solid #D9D9D9; transition: box-shadow .2s;
}
.order-card:active { box-shadow: 0 2px 8px rgba(0,0,0,.08); }

.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-no { font-size: 14px; font-weight: 600; color: #1D2129; font-family: monospace; }

.card-body { font-size: 14px; color: #4E5969; margin-bottom: 8px; line-height: 1.4; }
.card-footer { display: flex; gap: 12px; font-size: 12px; color: #C9CDD4; }
.card-device { color: #3491FA; font-family: monospace; }

.empty-state { text-align: center; padding: 60px 0; color: #C9CDD4; }
.empty-icon { font-size: 48px; margin-bottom: 8px; }
.empty-text { font-size: 15px; }
</style>
