<template>
  <div class="layout">
    <!-- 顶栏 (56px) -->
    <header class="topbar">
      <div class="topbar-left">
        <div class="logo-area">
          <div class="logo-icon">
            <el-icon :size="20" color="#fff"><Setting /></el-icon>
          </div>
          <span class="system-name">维修知识管理</span>
        </div>
      </div>
      <div class="topbar-right">
        <!-- 消息通知 -->
        <el-popover
          placement="bottom-end"
          :width="380"
          trigger="click"
          :visible="noticeVisible"
          @show="noticeVisible = true"
          @hide="noticeVisible = false"
          popper-class="notice-popover"
        >
          <template #reference>
            <el-badge :value="unreadCount" :max="99" :hidden="unreadCount === 0" class="notice-badge">
              <el-icon :size="20" @click="noticeVisible = !noticeVisible"><Bell /></el-icon>
            </el-badge>
          </template>
          <div class="notice-panel">
            <div class="notice-header">
              <span class="notice-title">消息通知</span>
              <el-button v-if="unreadCount > 0" text size="small" type="primary" @click="markAllRead">
                全部已读
              </el-button>
            </div>
            <div class="notice-tabs">
              <span
                v-for="tab in noticeTabs"
                :key="tab.key"
                class="notice-tab"
                :class="{ active: noticeTab === tab.key }"
                @click="noticeTab = tab.key"
              >{{ tab.label }}</span>
            </div>
            <div class="notice-list">
              <template v-if="filteredNotices.length === 0">
                <div class="notice-empty">
                  <el-icon :size="36" color="#C9CDD4"><Bell /></el-icon>
                  <p>暂无通知</p>
                </div>
              </template>
              <div
                v-for="item in filteredNotices"
                :key="item.id"
                class="notice-item"
                :class="{ unread: !item.read }"
                @click="handleNoticeClick(item)"
              >
                <div class="notice-dot" :class="item.type"></div>
                <div class="notice-body">
                  <div class="notice-item-title">{{ item.title }}</div>
                  <div class="notice-item-desc">{{ item.content }}</div>
                  <div class="notice-item-time">{{ item.time }}</div>
                </div>
              </div>
            </div>
            <div class="notice-footer">
              <el-button text size="small" type="primary" @click="$router.push('/notifications')">
                查看全部通知
              </el-button>
            </div>
          </div>
        </el-popover>

        <!-- 个人信息 -->
        <el-dropdown trigger="click" popper-class="user-dropdown">
          <span class="user-area">
            <el-avatar :size="32" icon="UserFilled" class="user-avatar" />
            <div class="user-info-text">
              <span class="user-name">{{ currentUser.name }}</span>
              <span class="user-role">{{ currentUser.roleLabel }}</span>
            </div>
            <el-icon class="arrow-down"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <div class="user-dropdown-panel">
              <!-- 用户信息头 -->
              <div class="ud-header">
                <el-avatar :size="44" icon="UserFilled" />
                <div class="ud-header-info">
                  <div class="ud-header-name">{{ currentUser.name }}</div>
                  <div class="ud-header-id">工号：{{ currentUser.employeeId }}</div>
                </div>
              </div>
              <div class="ud-divider"></div>
              <div class="ud-menu-list">
                <div class="ud-menu-item" @click="openProfile">
                  <el-icon :size="16"><User /></el-icon>
                  <span>个人设置</span>
                </div>
                <div class="ud-menu-item" @click="openSecurity">
                  <el-icon :size="16"><Lock /></el-icon>
                  <span>账号安全</span>
                </div>
                <div class="ud-menu-item" @click="openHelp">
                  <el-icon :size="16"><QuestionFilled /></el-icon>
                  <span>帮助中心</span>
                </div>
              </div>
              <div class="ud-divider"></div>
              <div class="ud-menu-list">
                <div class="ud-menu-item logout" @click="handleLogout">
                  <el-icon :size="16"><SwitchButton /></el-icon>
                  <span>退出登录</span>
                </div>
              </div>
            </div>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="layout-body">
      <!-- 侧边栏 (220px) -->
      <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <template v-if="!sidebarCollapsed">
          <!-- Logo 区 -->
          <div class="sidebar-logo">
            <div class="sidebar-logo-icon">
              <el-icon :size="18" color="#fff"><Setting /></el-icon>
            </div>
            <span class="sidebar-logo-text">管理台</span>
          </div>

          <!-- 菜单 -->
          <el-menu
            :default-active="activeMenu"
            router
            :collapse="sidebarCollapsed"
            background-color="#FFFFFF"
            text-color="#4E5969"
            active-text-color="#0FC6C2"
            class="sidebar-menu"
          >
            <!-- 主管：精简菜单，只留职责相关 -->
            <template v-if="isPureSupervisor">
              <div class="menu-group-label">工作台</div>
              <el-menu-item index="/dashboard">
                <el-icon><DataAnalysis /></el-icon>
                <template #title>数据驾驶舱</template>
              </el-menu-item>
              <el-menu-item index="/work-orders">
                <el-icon><Document /></el-icon>
                <template #title>维修报表</template>
              </el-menu-item>

              <div class="menu-group-label">基础数据</div>
              <el-menu-item index="/devices">
                <el-icon><Monitor /></el-icon>
                <template #title>设备监控</template>
              </el-menu-item>

              <div class="menu-group-label">主管中心</div>
              <el-menu-item index="/supervisor/dispatch">
                <el-icon><SetUp /></el-icon>
                <template #title>派工中心</template>
              </el-menu-item>
              <el-menu-item index="/supervisor/progress">
                <el-icon><Histogram /></el-icon>
                <template #title>实时进度看板</template>
              </el-menu-item>
              <el-menu-item index="/supervisor/schedule">
                <el-icon><Calendar /></el-icon>
                <template #title>排班管理</template>
              </el-menu-item>
            </template>

            <!-- 管理员 / 维修员：全菜单 -->
            <template v-else>
              <div class="menu-group-label">工作台</div>
              <el-menu-item index="/dashboard">
                <el-icon><DataAnalysis /></el-icon>
                <template #title>数据驾驶舱</template>
              </el-menu-item>
              <el-menu-item index="/work-orders">
                <el-icon><Document /></el-icon>
                <template #title>维修报表</template>
              </el-menu-item>
              <el-menu-item index="/ai-assistant">
                <el-icon><ChatLineSquare /></el-icon>
                <template #title>AI 问答看板</template>
              </el-menu-item>

              <div class="menu-group-label">知识管理</div>
              <el-sub-menu index="/knowledge">
                <template #title>
                  <el-icon><Reading /></el-icon>
                  <span>知识库</span>
                </template>
                <el-menu-item index="/knowledge/list">知识列表</el-menu-item>
                <el-menu-item index="/knowledge/manuals">设备手册</el-menu-item>
              </el-sub-menu>

              <div class="menu-group-label">基础数据</div>
              <el-menu-item index="/devices">
                <el-icon><Monitor /></el-icon>
                <template #title>设备监控</template>
              </el-menu-item>
              <el-menu-item index="/categories">
                <el-icon><Grid /></el-icon>
                <template #title>分类管理</template>
              </el-menu-item>

              <div class="menu-group-label">库存管理</div>
              <el-menu-item index="/warehouse">
                <el-icon><Box /></el-icon>
                <template #title>仓库库存</template>
              </el-menu-item>

              <div class="menu-group-label">系统工具</div>
              <el-menu-item index="/fault-codes">
                <el-icon><Connection /></el-icon>
                <template #title>故障码管理</template>
              </el-menu-item>
              <el-menu-item v-if="isSupervisor || isTechnician" index="/work-order-imports">
                <el-icon><Upload /></el-icon>
                <template #title>历史工单导入</template>
              </el-menu-item>

              <template v-if="isSupervisor">
                <div class="menu-group-label">主管中心</div>
                <el-menu-item index="/supervisor/dispatch">
                  <el-icon><SetUp /></el-icon>
                  <template #title>派工中心</template>
                </el-menu-item>
                <el-menu-item index="/supervisor/progress">
                  <el-icon><Histogram /></el-icon>
                  <template #title>实时进度看板</template>
                </el-menu-item>
                <el-menu-item index="/supervisor/schedule">
                  <el-icon><Calendar /></el-icon>
                  <template #title>排班管理</template>
                </el-menu-item>
              </template>

              <div class="menu-group-label">其他</div>
              <el-menu-item index="/help">
                <el-icon><QuestionFilled /></el-icon>
                <template #title>帮助中心</template>
              </el-menu-item>
            </template>
          </el-menu>
        </template>

        <!-- 折叠态 -->
        <template v-else>
          <el-menu
              :default-active="activeMenu"
              router
              :collapse="sidebarCollapsed"
              background-color="#FFFFFF"
              text-color="#4E5969"
              active-text-color="#0FC6C2"
              class="sidebar-menu collapsed-menu"
            >
              <!-- 主管精简版 -->
              <template v-if="isPureSupervisor">
                <el-menu-item index="/dashboard">
                  <el-icon><DataAnalysis /></el-icon>
                </el-menu-item>
                <el-menu-item index="/work-orders">
                  <el-icon><Document /></el-icon>
                </el-menu-item>
                <el-menu-item index="/devices">
                  <el-icon><Monitor /></el-icon>
                </el-menu-item>
                <el-menu-item index="/supervisor/dispatch">
                  <el-icon><SetUp /></el-icon>
                </el-menu-item>
                <el-menu-item index="/supervisor/progress">
                  <el-icon><Histogram /></el-icon>
                </el-menu-item>
                <el-menu-item index="/supervisor/schedule">
                  <el-icon><Calendar /></el-icon>
                </el-menu-item>
              </template>
              <!-- 管理员/维修员完整版 -->
              <template v-else>
                <el-menu-item index="/dashboard">
                  <el-icon><DataAnalysis /></el-icon>
                </el-menu-item>
                <el-menu-item index="/work-orders">
                  <el-icon><Document /></el-icon>
                </el-menu-item>
                <el-menu-item index="/ai-assistant">
                  <el-icon><ChatLineSquare /></el-icon>
                </el-menu-item>
                <el-sub-menu index="/knowledge">
                  <template #title>
                    <el-icon><Reading /></el-icon>
                  </template>
                  <el-menu-item index="/knowledge/list">知识列表</el-menu-item>
                  <el-menu-item index="/knowledge/manuals">设备手册</el-menu-item>
                </el-sub-menu>
                <el-menu-item index="/devices">
                  <el-icon><Monitor /></el-icon>
                </el-menu-item>
                <el-menu-item index="/categories">
                  <el-icon><Grid /></el-icon>
                </el-menu-item>
                <el-menu-item index="/warehouse">
                  <el-icon><Box /></el-icon>
                </el-menu-item>
                <el-menu-item index="/fault-codes">
                  <el-icon><Connection /></el-icon>
                </el-menu-item>
                <el-menu-item v-if="isSupervisor || isTechnician" index="/work-order-imports">
                  <el-icon><Upload /></el-icon>
                </el-menu-item>
                <template v-if="isSupervisor">
                  <el-menu-item index="/supervisor/dispatch">
                    <el-icon><SetUp /></el-icon>
                  </el-menu-item>
                  <el-menu-item index="/supervisor/progress">
                    <el-icon><Histogram /></el-icon>
                  </el-menu-item>
                  <el-menu-item index="/supervisor/schedule">
                    <el-icon><Calendar /></el-icon>
                  </el-menu-item>
                </template>
                <el-menu-item index="/help">
                  <el-icon><QuestionFilled /></el-icon>
                </el-menu-item>
              </template>
            </el-menu>
        </template>

        <!-- 折叠按钮 -->
        <div class="sidebar-footer" @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon :size="16">
            <Fold v-if="!sidebarCollapsed" />
            <Expand v-else />
          </el-icon>
          <span v-if="!sidebarCollapsed" class="collapse-text">收起侧栏</span>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="main-content">
        <div class="page-container">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'
import {
  User, Lock, QuestionFilled, SwitchButton,
  SetUp, Histogram, Calendar, Upload,
  DataAnalysis, Document, ChatLineSquare, Reading, Monitor, Grid, Box, Connection
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const sidebarCollapsed = ref(false)

const activeMenu = computed(() => {
  const path = route.path
  if (path.startsWith('/work-orders')) return '/work-orders'
  if (path.startsWith('/devices')) return '/devices'
  if (path.startsWith('/knowledge/manuals')) return '/knowledge/manuals'
  if (path.startsWith('/knowledge/list')) return '/knowledge/list'
  if (path.startsWith('/knowledge')) return '/knowledge'
  if (path.startsWith('/ai-assistant')) return '/ai-assistant'
  if (path.startsWith('/categories')) return '/categories'
  if (path.startsWith('/warehouse')) return '/warehouse'
  if (path.startsWith('/supervisor')) return path
  return path
})

const isSupervisor = computed(() => {
  const role = currentUser.role
  return role === 'SUPERVISOR' || role === 'ADMIN'
})

// 纯主管（仅 SUPERVISOR，不含 ADMIN）：菜单精简版
const isPureSupervisor = computed(() => currentUser.role === 'SUPERVISOR')

// 维修员（TECHNICIAN）：历史工单导入等负责核对确认的功能
const isTechnician = computed(() => currentUser.role === 'TECHNICIAN')

// ===== 当前用户 =====
const currentUser = reactive({
  id: null,
  name: '管理员',
  role: 'ADMIN',
  roleLabel: '系统管理员',
  employeeId: 'EMP001',
  avatar: '',
  department: '维修技术部',
  email: 'admin@company.com',
  phone: '138-0000-0001',
})

const fetchCurrentUser = async () => {
  try {
    // 后续接入登录态后从 API 获取
    const saved = localStorage.getItem('current_user')
    if (saved) {
      const data = JSON.parse(saved)
      Object.assign(currentUser, data)
    }
  } catch { /* ignore */ }
}

// ===== 消息通知（真实 API）=====
const noticeVisible = ref(false)
const noticeTab = ref('all')
const noticeTabs = [
  { key: 'all', label: '全部' },
  { key: 'system', label: '系统' },
  { key: 'work_order', label: '工单' },
]

const notices = ref([])
const unreadCount = ref(0)
let noticePollTimer = null

// 相对时间格式化
const formatNoticeTime = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr.replace(' ', 'T'))
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`
  return dateStr.slice(5, 16)
}

const filteredNotices = computed(() => {
  if (noticeTab.value === 'all') return notices.value
  return notices.value.filter(n => n.type === noticeTab.value)
})

const fetchUnreadCount = async () => {
  try {
    const res = await request.get('/notifications/unread-count', { timeout: 120000 })
    unreadCount.value = res.count || 0
  } catch { /* 静默 */ }
}

const fetchNotifications = async () => {
  try {
    const res = await request.get('/notifications/', { params: { page: 1, page_size: 20 }, timeout: 120000 })
    notices.value = (res.items || []).map(n => ({
      ...n,
      read: n.is_read,
      time: formatNoticeTime(n.created_at),
    }))
  } catch { /* 静默 */ }
}

const markAllRead = async () => {
  try {
    await request.post('/notifications/read-all', {}, { timeout: 120000 })
    notices.value.forEach(n => { n.read = true; n.is_read = true })
    unreadCount.value = 0
    ElMessage.success('已全部标记为已读')
  } catch { ElMessage.error('操作失败') }
}

const handleNoticeClick = async (item) => {
  try {
    if (!item.is_read) {
      await request.post(`/notifications/${item.id}/read`, {}, { timeout: 120000 })
      item.is_read = true
      item.read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  } catch { /* 静默 */ }
  noticeVisible.value = false
  // 根据通知类型跳转
  if (item.type === 'work_order') {
    router.push('/work-orders')
  } else {
    router.push('/dashboard')
  }
}

// ===== 个人信息操作 =====
const openProfile = () => {
  router.push('/profile')
}

const openSecurity = () => {
  router.push('/security')
}

const openHelp = () => {
  router.push('/help')
}

const handleLogout = async () => {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出确认', {
      confirmButtonText: '确定退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
    localStorage.removeItem('auth_token')
    localStorage.removeItem('current_user')
    ElMessage.success('已退出登录')
    router.push('/login')
  } catch { /* 取消 */ }
}

onMounted(() => {
  fetchCurrentUser()
  fetchUnreadCount()
  // 每 30 秒轮询未读数
  noticePollTimer = setInterval(fetchUnreadCount, 30000)
})

onUnmounted(() => {
  if (noticePollTimer) { clearInterval(noticePollTimer); noticePollTimer = null }
})

// 打开通知面板时拉取列表
watch(noticeVisible, (val) => {
  if (val) fetchNotifications()
})

// 路由变化时重新同步用户信息 + 刷新未读数
watch(() => route.path, () => {
  fetchCurrentUser()
  fetchUnreadCount()
})
</script>

<style scoped>
.layout { height:100%; display:flex; flex-direction:column; }

/* ===== 顶栏 ===== */
.topbar {
  height: 56px;
  background: #FFFFFF;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
  z-index: 100;
}
.topbar-left { display:flex; align-items:center; }
.logo-area { display:flex; align-items:center; gap:10px; }
.logo-icon {
  width: 32px; height: 32px;
  background: var(--color-primary);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
}
.system-name { font-size:16px; font-weight:600; color:var(--color-text-primary); white-space:nowrap; }
.topbar-right { display:flex; align-items:center; gap:16px; flex-shrink:0; }
.notice-badge { cursor:pointer; }
.user-area {
  display:flex; align-items:center; gap:8px; cursor:pointer;
  padding:4px 10px; border-radius:6px; transition:background .2s;
}
.user-area:hover { background:#F7F8FA; }
.user-avatar { flex-shrink:0; }
.user-info-text { display:flex; flex-direction:column; line-height:1.3; }
.user-name { font-size:14px; color:var(--color-text-primary); font-weight:500; }
.user-role { font-size:11px; color:var(--color-text-tertiary); }
.arrow-down { color:var(--color-text-disabled); font-size:12px; margin-left:-2px; }

/* ===== 主体 ===== */
.layout-body { flex:1; display:flex; overflow:hidden; }

/* ===== 侧边栏 ===== */
.sidebar {
  width: 220px;
  background: #FFFFFF;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width .2s;
  overflow: hidden;
  border-right: 1px solid var(--color-sidebar-border);
}
.sidebar.collapsed { width: 64px; }

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-sidebar-border);
}
.sidebar-logo-icon {
  width: 28px; height: 28px;
  background: var(--color-primary);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
}
.sidebar-logo-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.sidebar-menu {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 0;
}
.sidebar-menu :deep(.el-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: 2px 12px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--color-sidebar-text) !important;
  transition: background .15s, color .15s;
}
.sidebar-menu :deep(.el-menu-item .el-icon) {
  font-size: 18px;
  margin-right: 10px;
}
.sidebar-menu :deep(.el-menu-item:hover) {
  background-color: #F7F8FA !important;
  color: var(--color-text-primary) !important;
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--color-sidebar-active-bg) !important;
  color: var(--color-sidebar-active-text) !important;
  font-weight: 500;
}
.sidebar-menu :deep(.el-menu-item.is-active .el-icon) {
  color: var(--color-sidebar-active-text);
}

.sidebar-menu :deep(.el-sub-menu__title) {
  height: 40px;
  line-height: 40px;
  margin: 2px 12px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--color-sidebar-text) !important;
  transition: background .15s, color .15s;
}
.sidebar-menu :deep(.el-sub-menu__title:hover) {
  background: #F7F8FA !important;
  color: var(--color-text-primary) !important;
}
.sidebar-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--color-sidebar-active-text) !important;
  font-weight: 500;
}

.sidebar.collapsed :deep(.el-menu-item) {
  margin: 2px 8px;
  justify-content: center;
}
.sidebar.collapsed :deep(.el-menu-item .el-icon) {
  margin-right: 0;
}
.sidebar.collapsed :deep(.el-sub-menu__title) {
  margin: 2px 8px;
  justify-content: center;
}
.sidebar.collapsed :deep(.el-sub-menu__title .el-icon) {
  margin-right: 0;
}

.collapsed-menu { padding-top: 12px; }

/* 分组标签 */
.menu-group-label {
  padding: 16px 20px 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-sidebar-group);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 折叠区域 */
.sidebar-footer {
  border-top: 1px solid var(--color-sidebar-border);
  padding: 12px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: color .2s;
  user-select: none;
}
.sidebar-footer:hover { color: var(--color-primary); }
.collapse-text { font-size: 12px; }

/* ===== 主内容区 ===== */
.main-content { flex:1; overflow-y:auto; background:var(--color-bg-page); }
.page-container { padding:var(--spacing-page); min-height:100%; }
</style>

<style>
/* ===== 通知弹窗（全局覆盖 el-popover 样式） ===== */
.notice-popover {
  padding: 0 !important;
}
.notice-panel {
  display: flex;
  flex-direction: column;
}
.notice-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px 12px;
  border-bottom: 1px solid #E5E6EB;
}
.notice-title {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
}
.notice-tabs {
  display: flex;
  gap: 0;
  padding: 0 16px;
  border-bottom: 1px solid #E5E6EB;
}
.notice-tab {
  padding: 8px 16px;
  font-size: 13px;
  color: #86909C;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all .2s;
  user-select: none;
}
.notice-tab:hover {
  color: #4E5969;
}
.notice-tab.active {
  color: #0FC6C2;
  border-bottom-color: #0FC6C2;
  font-weight: 500;
}
.notice-list {
  max-height: 340px;
  overflow-y: auto;
}
.notice-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  color: #C9CDD4;
  font-size: 13px;
}
.notice-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background .15s;
  border-bottom: 1px solid #F2F3F5;
}
.notice-item:last-child {
  border-bottom: none;
}
.notice-item:hover {
  background: #F7F8FA;
}
.notice-item.unread {
  background: #F0FDFA;
}
.notice-item.unread:hover {
  background: #E6FAF7;
}
.notice-dot {
  width: 8px;
  height: 8px;
  min-width: 8px;
  border-radius: 50%;
  margin-top: 6px;
}
.notice-dot.work_order {
  background: #0FC6C2;
}
.notice-dot.system {
  background: #3370FF;
}
.notice-body {
  flex: 1;
  min-width: 0;
}
.notice-item-title {
  font-size: 14px;
  font-weight: 500;
  color: #1D2129;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notice-item.unread .notice-item-title {
  font-weight: 600;
}
.notice-item-desc {
  font-size: 13px;
  color: #4E5969;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}
.notice-item-time {
  font-size: 11px;
  color: #C9CDD4;
}
.notice-footer {
  border-top: 1px solid #E5E6EB;
  padding: 10px 16px;
  text-align: center;
}

/* ===== 用户下拉面板 ===== */
.user-dropdown {
  padding: 0 !important;
  min-width: 220px !important;
}
.user-dropdown-panel {
  padding: 4px 0;
}
.ud-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
}
.ud-header-info {
  flex: 1;
  min-width: 0;
}
.ud-header-name {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
  margin-bottom: 2px;
}
.ud-header-role {
  font-size: 12px;
  color: #0FC6C2;
  background: #E6FAF7;
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
}
.ud-header-id {
  font-size: 12px;
  color: #86909C;
}
.ud-divider {
  height: 1px;
  background: #F2F3F5;
  margin: 4px 0;
}
.ud-menu-list {
  padding: 4px 0;
}
.ud-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 16px;
  font-size: 14px;
  color: #1D2129;
  cursor: pointer;
  transition: background .15s;
}
.ud-menu-item:hover {
  background: #F7F8FA;
}
.ud-menu-item .el-icon {
  color: #4E5969;
}
.ud-menu-item.logout {
  color: #F53F3F;
}
.ud-menu-item.logout .el-icon {
  color: #F53F3F;
}
.ud-menu-item.logout:hover {
  background: #FFECEC;
}
</style>
