<template>
  <div class="page">
    <div class="knowledge-layout">
      <!-- 右侧知识列表 -->
      <div class="list-area">
        <el-card class="filter-card" shadow="never">
          <div class="filter-bar">
            <el-input v-model="keyword" placeholder="搜索知识标题/内容" clearable class="filter-input" @clear="handleSearch" @keyup.enter="handleSearch" />
            <el-select v-model="statusFilter" placeholder="状态筛选" clearable class="filter-select" @change="handleSearch">
              <el-option label="已发布" value="PUBLISHED" />
              <el-option label="已过期" value="DEPRECATED" />
            </el-select>
            <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
            <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
          </div>
        </el-card>

        <div class="knowledge-list" v-loading="loading">
          <template v-for="item in list" :key="item.id">
            <el-card class="knowledge-item" shadow="never">
            <div class="item-main">
              <div class="item-header">
                <h3 class="item-title">{{ item.title }}</h3>
                <span class="status-tag" :class="'status-' + item.status">{{ statusLabel(item.status) }}</span>
                <el-tag v-if="item.source_type === 'WORK_ORDER'" size="small" type="info" effect="plain">
                  工单提取
                </el-tag>
              </div>
              <p class="item-summary" v-if="item.content">{{ item.content.slice(0, 120) }}{{ item.content.length > 120 ? '...' : '' }}</p>
              <div class="item-meta">
                <span v-if="item.fault_code">故障码: {{ item.fault_code }}</span>
                <span v-if="item.device_type">适用设备: {{ item.device_type }}</span>
                <span>版本: v{{ item.version || 1 }}</span>
                <span>更新于: {{ formatTime(item.updated_at) }}</span>
              </div>
            </div>
            <div class="item-actions">
              <!-- 知识库只读：仅查看与去重检测，禁止编辑/删除/标记过期 -->
              <el-button size="small" type="primary" @click="$router.push(`/knowledge/${item.id}`)">查看</el-button>
              <el-button size="small" type="info" :loading="item._checking" @click="handleDedupCheck(item)">
                去重
              </el-button>
            </div>
          </el-card>
          </template>
          <el-empty v-if="!loading && list.length === 0" description="暂无知识条目" />
        </div>

        <div class="pagination-wrap" v-if="total > pageSize">
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="fetchData"
          />
        </div>
      </div>
    </div>

    <!-- 去重检测弹窗 -->
    <el-dialog v-model="dedupDialog.visible" title="去重检测结果" width="560px">
      <div v-if="dedupDialog.data">
        <el-alert
          :type="dedupDialog.data.has_duplicate ? 'warning' : 'success'"
          :title="dedupDialog.data.has_duplicate ? '检测到相似知识条目' : '未检测到重复'"
          :description="`最高相似度: ${(dedupDialog.data.similarity_score * 100).toFixed(1)}%`"
          show-icon
          style="margin-bottom: 16px"
        />
        <el-table v-if="dedupDialog.data.matched_items?.length" :data="dedupDialog.data.matched_items" size="small">
          <el-table-column prop="knowledge_id" label="ID" width="60" />
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column label="相似度" width="90">
            <template #default="{ row }">
              <span :style="{ color: row.similarity >= 0.85 ? '#F53F3F' : '#FF7D00', fontWeight: 600 }">
                {{ (row.similarity * 100).toFixed(1) }}%
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api'
import dayjs from 'dayjs'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const dedupDialog = reactive({ visible: false, data: null })

const statusMap = {
  DRAFT: '草稿',
  UNDER_REVIEW: '审核中',
  PUBLISHED: '已发布',
  DEPRECATED: '已过期',
  ARCHIVED: '已归档'
}
const statusLabel = (s) => statusMap[s] || s
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await request.get('/knowledge/', { params })
    list.value = res.items
    total.value = res.total
  } catch { /* handled */ }
  finally { loading.value = false }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; statusFilter.value = ''; page.value = 1; fetchData() }

const handleDedupCheck = async (row) => {
  row._checking = true
  try {
    const res = await request.post(`/knowledge/${row.id}/check-duplicate`)
    dedupDialog.data = res
    dedupDialog.visible = true
  } catch { /* handled */ }
  finally { row._checking = false }
}

onMounted(() => { fetchData() })</script>

<style scoped>
.knowledge-layout { display: flex; gap: 0; align-items: flex-start; }

.list-area { width: 100%; min-width: 0; }
.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 220px; }
.filter-select { width: 130px; }
.action-btn { flex-shrink: 0; }

.knowledge-list { display: flex; flex-direction: column; gap: 16px; }
.knowledge-item { display: flex; justify-content: space-between; align-items: flex-start; }
.item-main { flex: 1; min-width: 0; }
.item-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.item-title { font-size: 16px; font-weight: 500; color: var(--color-text-primary); }
.item-summary { color: var(--color-text-secondary); font-size: 13px; margin-bottom: 8px; line-height: 1.5; }
.item-meta { display: flex; gap: 16px; font-size: 12px; color: var(--color-text-disabled); flex-wrap: wrap; }
.item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
  margin-left: 16px;
}

.status-tag {
  display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; line-height: 20px;
}
.status-DRAFT { background: #F2F3F5; color: #4E5969; }
.status-UNDER_REVIEW { background: #FFF3E8; color: #FF7D00; }
.status-PUBLISHED { background: #E8F8EE; color: #00B42A; }
.status-DEPRECATED { background: #FFECEC; color: #F53F3F; }
.status-ARCHIVED { background: #F2F3F5; color: #C9CDD4; }

.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
