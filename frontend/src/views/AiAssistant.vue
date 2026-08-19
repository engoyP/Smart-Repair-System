<template>
  <div class="ai-assistant">
    <!-- ===== 左侧历史会话面板 ===== -->
    <div class="history-panel">
      <div class="history-header">
        <h3 class="history-title">历史会话</h3>
        <el-button class="new-chat-btn" circle :icon="Plus" @click="startNewChat" />
      </div>

      <div class="history-search-box">
        <el-input
          v-model="historySearch"
          placeholder="搜索会话..."
          :prefix-icon="Search"
          size="small"
          clearable
        />
      </div>

      <div class="history-list" ref="historyListRef">
        <template v-if="filteredSessions.length === 0">
          <div class="history-empty">
            <el-icon :size="36" color="#C9CDD4"><Message /></el-icon>
            <p>暂无历史会话</p>
          </div>
        </template>

        <!-- 今天 -->
        <div v-for="group in groupedSessions" :key="group.label" class="history-group">
          <div class="group-label">{{ group.label }}</div>
          <div
            v-for="s in group.items"
            :key="s.id"
            class="history-item"
            :class="{ active: activeSessionId === s.id }"
            @click="switchSession(s)"
          >
            <div class="item-left">
              <span class="item-dot" :class="{ unread: s.unread }"></span>
              <div class="item-content">
                <!-- 编辑状态：输入框 -->
                <el-input
                  v-if="editingTitleId === s.id"
                  v-model="editingTitleValue"
                  size="small"
                  class="rename-input"
                  @keydown.enter.stop="saveRename(s)"
                  @keydown.esc.stop="cancelRename"
                  @blur="saveRename(s)"
                  @click.stop
                  autofocus
                />
                <!-- 正常显示：标题 + 编辑按钮 -->
                <div class="item-title-row">
                  <div class="item-title">{{ s.title }}</div>
                  <span class="item-type-badge" :class="s.type">{{ s.type === 'guided' ? '追踪' : s.type === 'expert' ? '专家' : '问答' }}</span>
                  <el-button
                    class="item-rename"
                    text
                    size="small"
                    :icon="Edit"
                    @click.stop="startRename(s)"
                  />
                </div>
                <div class="item-preview">{{ s.preview }}</div>
              </div>
            </div>
            <div class="item-right">
              <span class="item-time">{{ s.time }}</span>
              <el-button
                class="item-delete"
                text
                size="small"
                :icon="Delete"
                @click.stop="deleteSession(s.id)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 右侧主内容区 ===== -->
    <div class="main-area">
      <!-- 顶部标题栏 -->
      <div class="top-bar">
        <div class="top-bar-left">
          <h2 class="top-bar-title">AI 智能维修助手</h2>
          <div class="mode-switch">
            <span
              class="mode-tab"
              :class="{ active: repairMode === 'qa' }"
              @click="switchMode('qa')"
            >问答模式</span>
            <span
              class="mode-tab"
              :class="{ active: repairMode === 'guided' }"
              @click="switchMode('guided')"
            >追踪维修</span>
            <span
              class="mode-tab"
              :class="{ active: repairMode === 'expert' }"
              @click="switchMode('expert')"
            >专家模式</span>
          </div>
        </div>
      </div>

      <!-- ===== 三种模式介绍（可折叠，默认记住收起状态） ===== -->
      <div class="mode-intro" :class="{ collapsed: !modeIntroExpanded }">
        <div class="mode-intro-title" @click="toggleModeIntro">
          <span class="mi-label">三种模式怎么选？</span>
          <span class="mi-tip">{{ modeIntroExpanded ? '点击卡片切换模式，点标题栏收起' : '点击展开查看适用场景' }}</span>
          <el-icon class="mi-arrow" :class="{ expanded: modeIntroExpanded }"><ArrowDown /></el-icon>
        </div>
        <el-collapse-transition>
          <div v-show="modeIntroExpanded" class="mode-intro-cards">
            <div
              v-for="card in modeIntroCards"
              :key="card.mode"
              class="mode-intro-card"
              :class="{ active: repairMode === card.mode }"
              @click="switchMode(card.mode)"
            >
              <div class="mi-card-head">
                <div class="mi-icon" :style="{ background: card.color }">
                  <el-icon :size="16" color="#fff"><component :is="card.icon" /></el-icon>
                </div>
                <span class="mi-name">{{ card.name }}</span>
              </div>
              <div class="mi-when"><span class="mi-when-label">适合</span>{{ card.when }}</div>
              <div class="mi-example"><span class="mi-example-label">例如</span>{{ card.example }}</div>
              <div class="mi-desc">{{ card.desc }}</div>
            </div>
          </div>
        </el-collapse-transition>
      </div>

      <!-- ===== 聊天内容区（问答/追踪共用） ===== -->

      <!-- 聊天内容区 -->
      <div class="chat-content" ref="chatContentRef">
        <!-- 空会话欢迎提示 -->
        <div v-if="!currentSession?.messages?.length" class="welcome-area">
          <div class="welcome-icon">
            <el-icon :size="40" color="#0FC6C2"><ChatLineSquare /></el-icon>
          </div>
          <h3>{{ repairMode === 'guided' ? '追踪维修模式' : repairMode === 'expert' ? '专家问答模式' : '向 AI 助手提问' }}</h3>
          <p>{{ repairMode === 'guided' ? '描述设备故障现象，AI 将逐步引导排查和维修' : repairMode === 'expert' ? 'AI 多轮智能检索知识库，先给出深入分析，再像老师傅一样逐步引导排查' : '描述设备故障现象，AI 将检索知识库中的维修案例和解决方案' }}</p>
          <div class="quick-hints">
            <span
              v-for="tag in quickTags"
              :key="tag"
              class="quick-hint"
              @click="sendMessage(tag)"
            >{{ tag }}</span>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-else class="message-area">
          <div
            v-for="(msg, idx) in currentSession.messages"
            :key="idx"
            class="message-row"
            :class="msg.role"
          >
            <!-- AI 消息 -->
            <div v-if="msg.role === 'assistant'" class="msg-wrapper">
              <div class="msg-ai-avatar">
                <div class="ai-av-inner"><el-icon :size="18" color="#fff"><ChatLineSquare /></el-icon></div>
              </div>
              <div class="msg-bubble-wrap">
                <div class="msg-bubble ai-msg-bubble">
                  <div v-if="msg._loading" class="thinking">
                    <span class="think-dot"></span>
                    <span class="think-dot"></span>
                    <span class="think-dot"></span>
                    <span class="think-text">正在思考中...</span>
                  </div>
                  <div v-else-if="msg._thinking" class="thinking">
                    <span class="think-dot"></span>
                    <span class="think-dot"></span>
                    <span class="think-dot"></span>
                    <span class="think-text">正在思考中...</span>
                  </div>
                  <div class="msg-text" v-html="renderMarkdown(msg.content)"></div>
                  <template v-if="!msg._loading && !msg._thinking">
                    <!-- 多故障提示：建议切专家模式 -->
                    <div v-if="msg._suggestExpert && !sending" class="suggest-expert">
                      <span class="suggest-text">检测到提问包含多个故障现象，专家模式会分故障逐一检索分析</span>
                      <el-button class="suggest-btn" size="small" @click="switchToExpert(msg._question)">切换到专家模式</el-button>
                    </div>
                    <!-- 匹配度标识 -->
                    <div v-if="msg.meta?.confidence" class="msg-confidence">
                      <span class="confidence-label">匹配度</span>
                      <span class="confidence-value" :class="getConfidenceClass(msg.meta.confidence)">
                        {{ (msg.meta.confidence * 100).toFixed(0) }}%
                      </span>
                    </div>
                    <!-- 参考案例 -->
                    <div v-if="msg.results?.length" class="msg-sources">
                      <div class="sources-title">
                        参考案例 ({{ msg.results.length }})
                        <span class="sources-hint">点击查看详情</span>
                      </div>
                      <div
                        v-for="item in msg.results"
                        :key="(item.source_type || 'CASE') + '-' + item.knowledge_id"
                        class="source-chip"
                        @click="showSourceDetail(item)"
                      >
                        <span
                          class="chip-tag chip-source"
                          :class="item.source_type === 'MANUAL' ? 'chip-source-manual' : 'chip-source-case'"
                        >{{ item.source_type === 'MANUAL' ? '手册' : '案例' }}</span>
                        <span class="chip-tag chip-fault" v-if="item.fault">{{ item.fault }}</span>
                        <span class="chip-tag chip-err" v-if="item.error_code">{{ item.error_code }}</span>
                        <span class="chip-tag" v-if="item.device_type">{{ item.device_type }}</span>
                        <span class="chip-title">{{ item.title }}</span>
                        <span class="chip-score">{{ (item.score * 100).toFixed(0) }}%</span>
                      </div>
                    </div>
                    <!-- 专家模式排查方向选项（纯文字展示，不提供点击） -->
                    <div v-if="msg.options?.length" class="msg-options">
                      <div class="options-title">排查方向<span class="options-hint">按顺序第 1 个为推荐</span></div>
                      <div
                        v-for="(opt, oi) in msg.options"
                        :key="opt.id || oi"
                        class="option-card"
                        :class="{ 'option-recommend': oi === 0 }"
                      >
                        <div class="option-head">
                          <span class="option-badge">{{ oi === 0 ? '推荐' : (opt.id || ('选项' + (oi + 1))) }}</span>
                          <span class="option-cause">{{ opt.cause }}</span>
                        </div>
                        <div class="option-action">{{ opt.diagnostic_action }}</div>
                      </div>
                    </div>
                    <!-- 性能指标 -->
                    <div v-if="msg.meta" class="msg-meta">
                      <span v-if="msg.meta.sourcesCount" class="meta-tag">案例 {{ msg.meta.sourcesCount }}</span>
                      <span v-if="msg.meta.retrievalTime" class="meta-tag">检索 {{ (msg.meta.retrievalTime / 1000).toFixed(1) }}s</span>
                      <span v-if="msg.meta.answerTime" class="meta-tag">生成 {{ (msg.meta.answerTime / 1000).toFixed(1) }}s</span>
                      <span class="meta-time">总计 {{ (msg.meta.totalTime / 1000).toFixed(1) }}s</span>
                    </div>
                  </template>
                </div>
              </div>
            </div>
            <!-- 摘要消息 -->
            <div v-else-if="msg.role === 'summary'" class="msg-wrapper">
              <div class="msg-ai-avatar">
                <div class="ai-av-inner summary"><el-icon :size="16" color="#fff"><Document /></el-icon></div>
              </div>
              <div class="msg-bubble-wrap">
                <div class="msg-bubble summary-bubble" @click="toggleSummaryExpand(currentSession.id, idx)">
                  <div class="summary-header">
                    <span class="summary-label">📋 对话摘要</span>
                    <span class="summary-badge">压缩 {{ msg._compressedCount }} 条</span>
                  </div>
                  <div v-if="expandedSummaries[`${currentSession.id}_${idx}`]" class="summary-body" v-html="renderMarkdown(msg.content)"></div>
                  <div v-else class="summary-collapsed">点击展开摘要详情</div>
                </div>
              </div>
            </div>

            <!-- 用户消息 -->
            <div v-else class="msg-wrapper user-wrapper">
              <div class="msg-bubble-wrap">
                <div class="msg-bubble user-msg-bubble">{{ msg.content }}</div>
              </div>
              <el-avatar :size="34" icon="UserFilled" />
            </div>
          </div>
        </div>
      </div>

      <!-- 底部输入区 -->
      <div class="input-area">
        <div class="quick-tags">
          <span
            v-for="tag in quickTags"
            :key="tag"
            class="quick-tag"
            @click="sendMessage(tag)"
          >{{ tag }}</span>
        </div>
        <div class="input-row">
          <div class="input-wrapper">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="1"
              :placeholder="repairMode === 'guided' ? '请输入操作结果和设备状态...' : repairMode === 'expert' ? '描述模糊或复杂的维修问题，专家模式将深度分析并引导排查...' : '请输入维修相关问题，规范的提问：产品型号+故障描述...'"
              class="chat-textarea"
              @keydown.enter.prevent.exact="handleSend"
              resize="none"
            />
          </div>
          <el-button
            class="send-circle-btn"
            :icon="Promotion"
            :loading="sending"
            :disabled="!inputText.trim()"
            @click="handleSend"
          />
        </div>
      </div>
    </div>

    <!-- 来源详情弹窗 -->
    <el-dialog v-model="sourceDialog.visible" :title="sourceDialog.item?.title" width="680px" destroy-on-close>
      <template v-if="sourceDialog.item">
        <div class="source-detail-meta">
          <el-tag
            v-if="sourceDialog.item.source_type"
            size="small"
            :type="sourceDialog.item.source_type === 'MANUAL' ? 'warning' : 'primary'"
            effect="plain"
          >{{ sourceDialog.item.source_type === 'MANUAL' ? '手册' : '案例' }}</el-tag>
          <el-tag v-if="sourceDialog.item.device_type" size="small" type="success" effect="plain">{{ sourceDialog.item.device_type }}</el-tag>
          <el-tag v-if="sourceDialog.item.error_code" size="small" type="danger" effect="plain">{{ sourceDialog.item.error_code }}</el-tag>
          <el-tag v-if="sourceDialog.item.fault_code" size="small" type="warning" effect="plain">{{ sourceDialog.item.fault_code }}</el-tag>
          <span class="source-detail-score">相关度 {{ (sourceDialog.item.score * 100).toFixed(0) }}%</span>
        </div>
        <!-- 手册出处：设备说明书/维修手册 + 章节 + 页码 -->
        <div v-if="sourceDialog.item.source_type === 'MANUAL'" class="source-detail-cite">
          <div class="cite-row"><span class="cite-label">手册</span>{{ sourceDialog.item.manual_name }}</div>
          <div class="cite-row"><span class="cite-label">章节</span>{{ sourceDialog.item.chapter }}</div>
          <div class="cite-row"><span class="cite-label">页码</span>{{ sourceDialog.item.page }}</div>
          <div class="cite-row"><span class="cite-label">错误码</span>{{ sourceDialog.item.error_code }}</div>
        </div>
        <div class="source-detail-content">{{ sourceDialog.item.content }}</div>
        <div v-if="sourceDialog.item.fault_tags?.length" class="source-detail-tags">
          <template v-for="t in sourceDialog.item.fault_tags" :key="t">
            <el-tag size="small">{{ t }}</el-tag>
          </template>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Plus, Search, Delete, Edit, Document, Message, Promotion, ChatLineSquare, Compass, Tools
} from '@element-plus/icons-vue'
import request from '../api'

const getStorageKey = () => {
  try {
    const raw = localStorage.getItem('current_user')
    if (raw) {
      const u = JSON.parse(raw)
      return `ai_assistant_sessions_${u.id}`
    }
  } catch {}
  return 'ai_assistant_sessions'
}
const chatContentRef = ref(null)
const historyListRef = ref(null)

const inputText = ref('')
const sending = ref(false)
const historySearch = ref('')
const activeSessionId = ref(null)
const currentSession = ref(null)
const sessions = ref([])
const sessionIdCounter = ref(0)

const sourceDialog = reactive({ visible: false, item: null })

// ===== 追踪模式 =====
const repairMode = ref('qa')

// ===== 三种模式介绍（维修人员视角） =====
const modeIntroCards = [
  {
    mode: 'qa',
    name: '智能问答',
    icon: ChatLineSquare,
    color: '#0FC6C2',
    when: '单个故障、问题描述得清，想快速知道"以前怎么处理的"',
    example: '"3号注塑机锁模力不够怎么办？"',
    desc: 'AI 检索历史案例，几秒给出「问题分析 → 可能原因 → 排查方向 → 处理方案 → 预防建议」五段式回答。一次问一个故障最快。',
  },
  {
    mode: 'guided',
    name: '追踪维修',
    icon: Compass,
    color: '#FF7D00',
    when: '故障复杂、说不出原因，或新人需要老师傅手把手带着查',
    example: '"注塑机报 E3091，帮我一步步查"',
    desc: 'AI 像老师傅一样逐步引导排查：每步给出操作建议和判断标准，你反馈结果后继续下一步，直到定位原因。',
  },
  {
    mode: 'expert',
    name: '专家模式',
    icon: Tools,
    color: '#3370FF',
    when: '一台设备同时出现多个故障，想一次性问清楚',
    example: '"锁模力不够出飞边，油温65度报警，熔胶马达不转，三个一起查"',
    desc: 'AI 把复合问题拆成多个单故障，分别检索各自的历史案例、按故障分组回答；并判断是否同根因、给出维修优先级，像老师傅一样逐步引导排查。',
  },
]

// ===== 模式介绍折叠面板（记住用户的展开/收起选择） =====
const MODE_INTRO_KEY = 'ai_mode_intro_collapsed'
const modeIntroExpanded = ref(localStorage.getItem(MODE_INTRO_KEY) !== '1')
const toggleModeIntro = () => {
  modeIntroExpanded.value = !modeIntroExpanded.value
  localStorage.setItem(MODE_INTRO_KEY, modeIntroExpanded.value ? '0' : '1')
}

const editingTitleId = ref(null)
const editingTitleValue = ref('')

// ===== 持久化 =====
const saveSessions = () => {
  try {
    // 只保存可序列化的数据，去掉 _loading 等临时状态
    const data = sessions.value.map(s => ({
      id: s.id,
      title: s.title,
      preview: s.preview,
      time: s.time,
      _group: s._group,
      _createdAt: s._createdAt,
      unread: false,
      type: s.type || 'qa',
      _expertSessionId: s._expertSessionId || '',   // 专家模式多轮会话 ID（随会话持久化）
      _guidedSessionId: s._guidedSessionId || '',   // 追踪模式引导会话 ID（随会话持久化），刷新后可接续多轮引导
      messages: s.messages.map(m => {
        if (m.role === 'assistant') {
          return {
            role: 'assistant',
            content: m.content,
            results: m.results || [],
            meta: m.meta || null,
            options: m.options || [],               // 专家模式排查方向选项
          }
        }
        if (m.role === 'summary') {
          return {
            role: 'summary',
            content: m.content,
            _compressedCount: m._compressedCount || 0,
            _timestamp: m._timestamp || Date.now(),
          }
        }
        return { role: 'user', content: m.content }
      }),
    }))
    localStorage.setItem(getStorageKey(), JSON.stringify(data))
  } catch (e) {
    console.error('保存会话失败:', e)
  }
}

const loadSessions = () => {
  try {
    const raw = localStorage.getItem(getStorageKey())
    if (!raw) {
      startNewChat()
      return
    }
    const data = JSON.parse(raw)
    if (!data.length) {
      startNewChat()
      return
    }
    // 按 _createdAt 重新计算分组
    const now = new Date()
    const todayStr = now.toDateString()
    const yesterdayStr = new Date(now.getTime() - 86400000).toDateString()
    for (const s of data) {
      const d = new Date(s._createdAt)
      s._group = d.toDateString() === todayStr ? 'today'
        : d.toDateString() === yesterdayStr ? 'yesterday' : formatDateLabel(d)
    }
    sessions.value = data
    // 恢复最后一个活跃会话
    const last = data[0]
    activeSessionId.value = last.id
    currentSession.value = last
    // 同步恢复模式：刷新后不能停在默认'qa'，否则追踪/专家会话会"对话不绑定"（消息仍发到问答流）
    repairMode.value = last.type || 'qa'
    // 恢复 sessionIdCounter
    const maxId = data.reduce((max, s) => {
      const n = parseInt(s.id.replace('session_', ''), 10)
      return n > max ? n : max
    }, 0)
    sessionIdCounter.value = maxId
  } catch (e) {
    console.error('加载会话失败:', e)
    startNewChat()
  }
}

onMounted(() => {
  loadSessions()
  scrollToBottom()
})

// 快捷标签
// ===== 模式切换 =====
const switchMode = (mode) => {
  if (repairMode.value === mode) return
  repairMode.value = mode
  if (currentSession.value) currentSession.value._expertSessionId = ''
  if (currentSession.value) currentSession.value._guidedSessionId = ''
  if (mode === 'guided') {
    startNewGuidedChat()
  } else if (mode === 'expert') {
    if (!currentSession.value || currentSession.value.type !== 'expert') {
      startNewExpertChat()
    }
  } else {
    if (!currentSession.value || currentSession.value.type === 'guided' || currentSession.value.type === 'expert') {
      startNewChat()
    }
  }
}

// 一键切换到专家模式并重新提问（问答模式检测到多故障时触发）
const switchToExpert = (question) => {
  repairMode.value = 'expert'
  startNewExpertChat()
  sendMessage(question || '')
}

const quickTags = [
  '查询轴承库存', '电机异响处理', '液压系统漏油',
  '3号机组故障', '温度偏高报警', 'CNC主轴维护',
]

// ===== 会话分组 =====
const filteredSessions = computed(() => {
  if (!historySearch.value) return sessions.value
  const kw = historySearch.value.toLowerCase()
  return sessions.value.filter(s =>
    s.title.toLowerCase().includes(kw) || s.preview.toLowerCase().includes(kw)
  )
})

const groupedSessions = computed(() => {
  const groups = []
  const today = [], yesterday = []
  const dateMap = {}

  for (const s of filteredSessions.value) {
    if (s._group === 'today') today.push(s)
    else if (s._group === 'yesterday') yesterday.push(s)
    else {
      const key = s._group || formatDateLabel(new Date(s._createdAt))
      if (!dateMap[key]) dateMap[key] = []
      dateMap[key].push(s)
    }
  }

  if (today.length) groups.push({ label: '今天', items: today })
  if (yesterday.length) groups.push({ label: '昨天', items: yesterday })
  for (const [label, items] of Object.entries(dateMap)) {
    groups.push({ label, items })
  }
  return groups
})

// ===== 工具函数 =====
const scrollToBottom = async () => {
  await nextTick()
  if (chatContentRef.value) {
    chatContentRef.value.scrollTop = chatContentRef.value.scrollHeight
  }
}

const renderMarkdown = (text) => {
  if (!text) return ''
  let html = text
    .replace(/### (.*)/g, '<h4 style="font-size:14px;font-weight:600;color:#1D2129;margin:12px 0 6px;">$1</h4>')
    .replace(/## (.*)/g, '<h3 style="font-size:15px;font-weight:600;color:#1D2129;margin:14px 0 8px;">$1</h3>')
    .replace(/\*\*(.*?)\*\*/g, '<strong style="color:#1D2129;">$1</strong>')
    .replace(/\n\n/g, '</p><p style="margin:6px 0;">')
    .replace(/\n(\d+)\.\s/g, '<br/>$1. ')
    .replace(/\n-\s/g, '<br/>- ')
    .replace(/\n/g, '<br/>')
  return `<p style="margin:0;">${html}</p>`
}

const getConfidenceClass = (score) => {
  if (score >= 0.7) return 'high'
  if (score >= 0.4) return 'medium'
  return 'low'
}

const formatTime = (d) => {
  const h = d.getHours().toString().padStart(2, '0')
  const m = d.getMinutes().toString().padStart(2, '0')
  return `${h}:${m}`
}

const formatDateLabel = (d) => {
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

// ===== 新建/切换会话 =====
const startNewChat = () => {
  sessionIdCounter.value++
  const id = `session_${sessionIdCounter.value}`
  const now = new Date()
  const session = {
    id,
    title: '新对话',
    preview: '',
    time: formatTime(now),
    _group: 'today',
    _createdAt: now,
    unread: false,
    type: 'qa',
    messages: [],
  }
  sessions.value.unshift(session)
  activeSessionId.value = id
  currentSession.value = session
  saveSessions()
}

const switchSession = async (s) => {
  activeSessionId.value = s.id
  currentSession.value = s
  s.unread = false
  repairMode.value = s.type || 'qa'
  s._guidedSessionId = ''   // 切换会话：追踪引导不接续旧会话，重新开始
  s._expertSessionId = ''
  await scrollToBottom()
}

const deleteSession = (id) => {
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (activeSessionId.value === id) {
    activeSessionId.value = sessions.value[0]?.id || null
    currentSession.value = sessions.value[0] || null
  }
  saveSessions()
}

const startNewGuidedChat = () => {
  sessionIdCounter.value++
  const id = `session_${sessionIdCounter.value}`
  const now = new Date()
  const session = {
    id,
    title: '追踪维修',
    preview: '',
    time: formatTime(now),
    _group: 'today',
    _createdAt: now,
    unread: false,
    type: 'guided',
    _guidedSessionId: '',
    messages: [],
  }
  sessions.value.unshift(session)
  activeSessionId.value = id
  currentSession.value = session
  saveSessions()
}

const startNewExpertChat = () => {
  sessionIdCounter.value++
  const id = `session_${sessionIdCounter.value}`
  const now = new Date()
  const session = {
    id,
    title: '专家问答',
    preview: '',
    time: formatTime(now),
    _group: 'today',
    _createdAt: now,
    unread: false,
    type: 'expert',
    messages: [],
  }
  sessions.value.unshift(session)
  activeSessionId.value = id
  currentSession.value = session
  saveSessions()
}

// ===== 切换会话 =====
const startRename = (s) => {
  editingTitleId.value = s.id
  editingTitleValue.value = s.title
}

const saveRename = (s) => {
  const val = editingTitleValue.value.trim()
  if (val) {
    s.title = val
    saveSessions()
  }
  editingTitleId.value = null
  editingTitleValue.value = ''
}

const cancelRename = () => {
  editingTitleId.value = null
  editingTitleValue.value = ''
}

// ===== 会话摘要压缩 =====
const COMPRESS_THRESHOLD = 16        // 超过此消息数触发压缩
const COMPRESS_KEEP_LATEST = 8       // 保留最新的 N 条消息不压缩
const COMPRESS_BATCH = 8             // 每次压缩多少条旧消息
const expandedSummaries = ref({})    // { sessionId_msgIdx: true/false }

const toggleSummaryExpand = (sessionId, msgIdx) => {
  const key = `${sessionId}_${msgIdx}`
  expandedSummaries.value[key] = !expandedSummaries.value[key]
}

const compressSession = async (session) => {
  if (!session || session._summarizing) return

  const msgs = session.messages
  // 只统计 user/assistant 消息数（排除已有的 summary）
  const normalMsgs = msgs.filter(m => m.role === 'user' || m.role === 'assistant')
  if (normalMsgs.length < COMPRESS_THRESHOLD) return

  // 找到需要压缩的旧消息索引范围（跳过 summary 类型的，只压缩最早的 user/assistant）
  let compressEnd = -1
  let count = 0
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i].role === 'user' || msgs[i].role === 'assistant') {
      count++
      if (count >= COMPRESS_BATCH) {
        compressEnd = i
        break
      }
    }
  }
  if (compressEnd < 0) return

  const toCompress = msgs.slice(0, compressEnd + 1).filter(m => m.role === 'user' || m.role === 'assistant')
  if (toCompress.length < 4) return

  session._summarizing = true
  try {
    const payload = {
      session_id: session.id,
      messages: toCompress.map(m => ({ role: m.role, content: m.content })),
    }
    const res = await request.post('/session/summarize', payload, { timeout: 60000 })
    const summaryText = res.summary || ''

    // 将压缩掉的消息替换为一个 summary 条目
    const summaryEntry = {
      role: 'summary',
      content: summaryText,
      _compressedCount: toCompress.length,
      _timestamp: Date.now(),
    }
    // 删除被压缩的消息，插入 summary
    msgs.splice(0, compressEnd + 1, summaryEntry)

    // 更新预览
    if (msgs.length > 0) {
      const last = msgs[msgs.length - 1]
      if (last.role === 'assistant') {
        session.preview = last.content?.slice(0, 40) + (last.content?.length > 40 ? '...' : '')
      }
    }
    saveSessions()
  } catch (e) {
    console.error('会话压缩失败:', e)
  } finally {
    session._summarizing = false
  }
}

// ===== 发送消息 =====
const sendMessage = (text) => {
  inputText.value = text
  handleSend()
}

const handleSend = async () => {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  if (!currentSession) {
    repairMode.value === 'guided' ? startNewGuidedChat() : startNewChat()
  }

  const session = currentSession.value
  if (!session) return

  const isGuided = repairMode.value === 'guided'

  session.messages.push({ role: 'user', content: text })
  inputText.value = ''
  await scrollToBottom()

  const aiMsg = reactive({
    role: 'assistant',
    _loading: true,
    content: '',
    results: [],
    meta: null,
    _suggestExpert: false,
    _question: text,
  })
  session.messages.push(aiMsg)

  session.title = text.length > 20 ? text.slice(0, 20) + '...' : text
  session.time = formatTime(new Date())
  await scrollToBottom()

  sending.value = true
  const startTime = Date.now()

  try {
    // 专家模式多轮：已有会话 ID 则走后续引导轮，否则走首轮
    const isExpertStep = repairMode.value === 'expert' && !!(session._expertSessionId || '')
    const url = isGuided
      ? '/api/v1/search/guided-repair/chat'
      : isExpertStep
        ? '/api/v1/search/answer/expert/step'
        : repairMode.value === 'expert'
          ? '/api/v1/search/answer/expert'
          : '/api/v1/search/answer/stream'
    const body = isGuided
      ? JSON.stringify({ message: text, session_id: session._guidedSessionId || undefined })
      : isExpertStep
        ? JSON.stringify({ session_id: session._expertSessionId, message: text })
        : JSON.stringify({ question: text, top_k: 8 })

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('auth_token') || '') },
      body,
    })

    if (!response.ok) {
      aiMsg._loading = false
      aiMsg._thinking = false
      aiMsg.content = '请求失败，请稍后重试。'
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let refsBuffer = ''
    let firstDataReceived = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        if (!isGuided && line.startsWith('event: references')) {
          if (i + 1 < lines.length && lines[i + 1].startsWith('data: ')) {
            try {
              aiMsg.results = JSON.parse(lines[i + 1].slice(6))
            } catch {}
            i++
          } else {
            refsBuffer = line
          }
          continue
        }
        if (line.startsWith('event: options')) {
          // 专家模式排查方向选项（首轮 /expert 与后续轮 /expert/step 都会发）
          if (i + 1 < lines.length && lines[i + 1].startsWith('data: ')) {
            try {
              aiMsg.options = JSON.parse(lines[i + 1].slice(6))
            } catch {}
            i++
          }
          continue
        }
        if (line.startsWith('event:')) continue
        if (refsBuffer && line.startsWith('data: ')) {
          try { aiMsg.results = JSON.parse(line.slice(6)) } catch {}
          refsBuffer = ''
          continue
        }
        if (line.startsWith('data: ')) {
          if (!firstDataReceived) {
            firstDataReceived = true
            aiMsg._loading = false
            aiMsg._thinking = true
          }
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'thinking') {
              aiMsg._thinking = true
              aiMsg._loading = false
            } else if (data.type === 'answer') {
              aiMsg._thinking = false
              aiMsg._loading = false
              aiMsg.content += data.content
            } else if (data.type === 'suggest_expert') {
              aiMsg._suggestExpert = true
            } else if (data.type === 'done') {
              aiMsg._thinking = false
              aiMsg._loading = false
              if (isGuided) {
                session._guidedSessionId = data.session_id || ''
              } else {
                if (data.session_id) {
                  // 专家模式首轮：记录会话 ID，后续轮走 /answer/expert/step
                  session._expertSessionId = data.session_id
                  // 如果本轮已解决（completed），清除会话 ID，下一次问题走新首轮
                  if (data.completed) {
                    session._expertSessionId = ''
                  }
                }
                aiMsg.meta = {
                  confidence: data.confidence,
                  sourcesCount: data.sources_count || aiMsg.results.length,
                  totalTime: Date.now() - startTime,
                }
              }
            }
          } catch { /* skip */ }
        }
      }
      await scrollToBottom()
    }

    session.preview = aiMsg.content.slice(0, 40) + (aiMsg.content.length > 40 ? '...' : '')
    await scrollToBottom()
    saveSessions()
    if (!isGuided) compressSession(session)
  } catch (e) {
    console.error('发送失败:', e)
    aiMsg._loading = false
    aiMsg.content = isGuided ? '追踪引导出现异常，请稍后重试。' : '检索过程出现异常，请稍后重试。'
    session.preview = isGuided ? '追踪异常' : '检索失败'
    ElMessage.error(isGuided ? '追踪失败' : '检索失败')
  } finally {
    sending.value = false
    await scrollToBottom()
    saveSessions()
  }
}

// ===== 来源详情 =====
const showSourceDetail = (item) => {
  sourceDialog.item = item
  sourceDialog.visible = true
}

// ===== 退出 =====
</script>

<style scoped>
.ai-assistant {
  display: flex;
  height: calc(100vh - 56px);
  background: var(--color-bg-page);
  font-family: var(--font-family);
  overflow: hidden;
}

/* ===== 左侧历史会话面板 ===== */
.history-panel {
  width: 260px;
  min-width: 260px;
  background: #FFFFFF;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 16px 12px;
}
.history-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.new-chat-btn {
  width: 30px; height: 30px;
  background: var(--color-primary);
  color: #fff;
  border: none;
}
.new-chat-btn:hover { background: var(--color-primary-hover); color: #fff; }

.history-search-box {
  padding: 0 16px 10px;
}
.history-search-box :deep(.el-input__wrapper) {
  border-radius: 6px;
  background: var(--color-bg-page);
  box-shadow: none;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 12px;
}
.history-list::-webkit-scrollbar { width: 4px; }
.history-list::-webkit-scrollbar-thumb { background: var(--color-text-disabled); border-radius: 2px; }

.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 60px 0;
  color: var(--color-text-disabled);
  font-size: 13px;
}

.history-group { margin-bottom: 8px; }
.group-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-disabled);
  padding: 8px 4px 4px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background .15s;
  margin-bottom: 2px;
}
.history-item:hover { background: var(--color-bg-page); }
.history-item.active { background: var(--color-primary-light); }

.item-left {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.item-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--color-text-disabled);
  margin-top: 6px;
  flex-shrink: 0;
}
.item-dot.unread { background: var(--color-primary); }

.item-content { flex: 1; min-width: 0; }
.item-title-row {
  display: flex;
  align-items: center;
  gap: 2px;
}
.item-title-row .item-title {
  flex: 1;
  min-width: 0;
}
.item-type-badge {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
  line-height: 16px;
}
.item-type-badge.qa {
  background: #E8F4FF;
  color: #3370FF;
}
.item-type-badge.guided {
  background: #D1F7F6;
  color: #0FC6C2;
}
.item-type-badge.expert {
  background: #FFF3E8;
  color: #FF7D00;
}
.item-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-preview {
  font-size: 12px;
  color: var(--color-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 2px;
}

.item-rename {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity .15s;
  color: var(--color-text-tertiary) !important;
  padding: 2px !important;
  min-width: unset !important;
  height: 20px !important;
  margin-left: 2px;
}
.history-item:hover .item-rename,
.active .item-rename { opacity: 1; }
.item-rename:hover { color: var(--color-primary) !important; }

.rename-input { width: 100%; }
.rename-input .el-input__inner {
  height: 26px;
  font-size: 12px;
  padding: 0 6px;
}

.item-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.item-time {
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}
.item-delete {
  opacity: 0;
  transition: opacity .15s;
  color: var(--color-text-tertiary);
}
.history-item:hover .item-delete { opacity: 1; }

/* ===== 右侧主内容区 ===== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-bg-page);
}

/* 顶部标题栏 */
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}
.top-bar-left { display: flex; align-items: center; gap: 16px; }
.top-bar-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}

/* ===== 欢迎区域 ===== */
.welcome-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px 40px;
  text-align: center;
}
.welcome-icon {
  width: 72px; height: 72px;
  background: var(--color-primary-light);
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 16px;
}
.welcome-area h3 {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}
.welcome-area p {
  font-size: 14px;
  color: var(--color-text-tertiary);
  max-width: 480px;
  line-height: 1.6;
  margin-bottom: 24px;
}
.quick-hints {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-width: 520px;
  justify-content: center;
}
.quick-hint {
  font-size: 13px;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 8px 18px;
  border-radius: 20px;
  cursor: pointer;
  transition: all .15s;
  border: 1px solid transparent;
}
.quick-hint:hover {
  background: #fff;
  border-color: var(--color-primary);
}

/* ===== 聊天消息区 ===== */
.chat-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
.chat-content::-webkit-scrollbar { width: 6px; }
.chat-content::-webkit-scrollbar-thumb { background: var(--color-text-disabled); border-radius: 3px; }

.message-area { max-width: 800px; margin: 0 auto; }

.message-row {
  margin-bottom: 20px;
}

/* AI 消息 */
.msg-wrapper.assistant {
  display: flex;
  gap: 10px;
}
.ai-av-inner { width: 34px; height: 34px; background: var(--color-primary); border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ai-av-inner.summary { background: #722ED1; }
.msg-bubble-wrap { flex: 1; min-width: 0; }
.ai-msg-bubble {
  background: #fff;
  border: 1px solid var(--color-border);
  border-radius: 8px 8px 8px 4px;
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
}
.msg-text {
  font-size: 14px;
  color: var(--color-text-primary);
  line-height: 1.8;
}

.msg-text p { margin: 4px 0; }
.msg-text h3 { margin: 14px 0 8px; }
.msg-text h4 { margin: 12px 0 6px; }
.msg-text strong { color: var(--color-text-primary); }

/* 摘要气泡 */
.summary-bubble {
  background: #F9F0FF;
  border: 1px solid #E8D4FF;
  border-radius: 8px 8px 8px 4px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background .15s;
}
.summary-bubble:hover { background: #F0E6FF; }
.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.summary-label { font-size: 13px; font-weight: 600; color: #722ED1; }
.summary-badge {
  font-size: 11px;
  color: #722ED1;
  background: rgba(114,46,209,0.1);
  padding: 1px 8px;
  border-radius: 8px;
}
.summary-collapsed { font-size: 12px; color: #9A6DDB; }
.summary-body {
  margin-top: 8px;
  font-size: 13px;
  color: #5B21B6;
  line-height: 1.7;
  border-top: 1px solid #E8D4FF;
  padding-top: 8px;
}

/* 多故障提示：建议切专家模式 */
.suggest-expert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  padding: 8px 12px;
  background: #FFF3E8;
  border: 1px solid #FFD8B5;
  border-radius: 8px;
}
.suggest-text {
  font-size: 12px;
  color: #B25000;
  line-height: 1.5;
  flex: 1;
}
.suggest-btn {
  background: #FF7D00 !important;
  border-color: #FF7D00 !important;
  color: #fff !important;
  font-weight: 500;
  flex-shrink: 0;
}
.suggest-btn:hover {
  background: #E86F00 !important;
  border-color: #E86F00 !important;
}

/* 匹配度 */
.msg-confidence {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border-light);
}
.confidence-label {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.confidence-value {
  font-size: 13px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 12px;
}
.confidence-value.high { color: var(--color-success); background: #E8F8EE; }
.confidence-value.medium { color: var(--color-warning); background: #FFF3E8; }
.confidence-value.low { color: var(--color-danger); background: #FFECEC; }

/* 参考案例标题 */
.sources-hint {
  font-size: 11px;
  color: var(--color-text-tertiary);
  font-weight: normal;
  margin-left: 4px;
}

/* 思考动画 */
.thinking {
  display: flex;
  align-items: center;
  gap: 4px;
}
.think-dot {
  width: 8px; height: 8px;
  background: var(--color-primary);
  border-radius: 50%;
  animation: thinkBounce 1.2s infinite ease-in-out;
}
.think-dot:nth-child(2) { animation-delay: .2s; }
.think-dot:nth-child(3) { animation-delay: .4s; }
@keyframes thinkBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: .4; }
  40% { transform: scale(1); opacity: 1; }
}
.think-text {
  font-size: 13px;
  color: var(--color-text-tertiary);
  margin-left: 8px;
}

/* 来源卡片 */
.msg-sources {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-light);
}
/* 专家模式排查方向选项 */
.msg-options {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-light);
}
.options-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}
.options-hint {
  margin-left: 8px;
  font-weight: 400;
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.option-card {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--color-bg-page);
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
}
.option-card.option-recommend {
  border-color: var(--color-primary);
  background: rgba(51, 112, 255, .05);
}
.option-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.option-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  color: var(--color-primary);
  background: rgba(51, 112, 255, .10);
  border-radius: 4px;
  font-weight: 600;
}
.option-card.option-recommend .option-badge {
  color: #fff;
  background: var(--color-primary);
}
.option-cause {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 20px;
}
.option-action {
  margin-top: 6px;
  padding-left: 34px;
  font-size: 12.5px;
  color: var(--color-text-secondary);
  line-height: 20px;
  white-space: pre-line;
}
.sources-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}
.source-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 6px;
  background: var(--color-bg-page);
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  cursor: pointer;
  transition: all .15s;
}
.source-chip:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
.chip-tag {
  font-size: 11px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  padding: 1px 8px;
  border-radius: 4px;
  font-weight: 500;
  flex-shrink: 0;
}
.chip-fault {
  background: #FFF3E8;
  color: #FF7D00;
}
/* 来源类型徽标：手册=橙色，案例=蓝色 */
.chip-source-manual {
  background: #FFF3E8;
  color: #FF7D00;
  border: 1px solid #FFD8B5;
}
.chip-source-case {
  background: var(--color-primary-light);
  color: var(--color-primary);
  border: 1px solid var(--color-primary-light);
}
/* 错误码 chip */
.chip-err {
  background: #FFF0F0;
  color: #F56C6C;
  font-weight: 600;
}
.chip-title {
  flex: 1;
  font-size: 13px;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-score {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

/* 消息元信息 */
.msg-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border-light);
}
.meta-tag {
  font-size: 11px;
  color: var(--color-text-tertiary);
  background: var(--color-bg-page);
  padding: 1px 8px;
  border-radius: 4px;
}
.meta-tag.rewrite { color: var(--color-warning); background: #FFF3E8; }
.meta-time {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-left: auto;
}

/* 用户消息 */
.user-wrapper {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-left: 60px;
}
.user-msg-bubble {
  background: var(--color-primary);
  color: #fff;
  padding: 12px 18px;
  border-radius: 8px 8px 4px 8px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

/* ===== 底部输入区 ===== */
.input-area {
  flex-shrink: 0;
  padding: 12px 24px 20px;
  background: #fff;
  border-top: 1px solid var(--color-border);
}
.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.quick-tag {
  font-size: 12px;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 4px 14px;
  border-radius: 14px;
  cursor: pointer;
  transition: all .15s;
  border: 1px solid transparent;
}
.quick-tag:hover {
  background: #fff;
  border-color: var(--color-primary);
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.input-wrapper {
  flex: 1;
}
.chat-textarea :deep(.el-textarea__inner) {
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
  padding: 10px 20px;
  min-height: 44px;
  max-height: 120px;
  resize: none;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border);
}
.chat-textarea :deep(.el-textarea__inner:focus) {
  border-color: var(--color-primary);
  box-shadow: 0 2px 8px rgba(15,198,194,0.12);
}

.send-circle-btn {
  width: 44px; height: 44px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  border: none;
  font-size: 20px;
  flex-shrink: 0;
  padding: 0;
}
.send-circle-btn:hover { background: var(--color-primary-hover); color: #fff; }
.send-circle-btn.is-disabled { background: var(--color-text-disabled); color: #fff; }

/* ===== 来源详情弹窗 ===== */
.source-detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.source-detail-score {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}
.source-detail-content {
  font-size: 15px;
  line-height: 1.8;
  color: var(--color-text-primary);
  white-space: pre-wrap;
}
.source-detail-tags {
  margin-top: 16px;
  display: flex;
  gap: 6px;
}
/* 手册出处区块 */
.source-detail-cite {
  margin-bottom: 16px;
  padding: 10px 14px;
  background: #FFF3E8;
  border: 1px solid #FFD8B5;
  border-radius: 8px;
  font-size: 13px;
  color: #B25000;
}
.cite-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  line-height: 1.9;
}
.cite-label {
  flex-shrink: 0;
  width: 48px;
  font-weight: 600;
  color: #FF7D00;
}

/* ===== 追踪维修模式 ===== */
.mode-switch {
  display: flex; gap: 4px; background: #F2F3F5; border-radius: 8px; padding: 3px;
  margin-left: 16px;
}
.mode-tab {
  padding: 5px 14px; border-radius: 6px; font-size: 13px; cursor: pointer;
  color: #86909C; font-weight: 500; transition: all .2s; white-space: nowrap;
}
.mode-tab:hover { color: #4E5969; }
.mode-tab.active { background: #fff; color: #0FC6C2; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

/* ===== 三种模式介绍 ===== */
.mode-intro {
  padding: 12px 24px 0;
  flex-shrink: 0;
}
.mode-intro.collapsed {
  padding-bottom: 8px;
}
.mode-intro-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  user-select: none;
}
.mode-intro.collapsed .mode-intro-title {
  margin-bottom: 0;
}
.mode-intro-title:hover .mi-label {
  color: #0FC6C2;
}
.mi-arrow {
  margin-left: auto;
  color: var(--color-text-secondary);
  transition: transform .3s;
}
.mi-arrow.expanded {
  transform: rotate(180deg);
}
.mi-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.mi-tip {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.mode-intro-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.mode-intro-card {
  background: #fff;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all .2s;
}
.mode-intro-card:hover {
  border-color: #0FC6C2;
  box-shadow: 0 2px 8px rgba(15, 198, 194, 0.12);
}
.mode-intro-card.active {
  border-color: #0FC6C2;
  background: rgba(15, 198, 194, 0.04);
}
.mi-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.mi-icon {
  width: 28px; height: 28px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.mi-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.mi-when,
.mi-example {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin-bottom: 2px;
}
.mi-when-label,
.mi-example-label {
  display: inline-block;
  font-size: 11px;
  padding: 0 4px;
  border-radius: 3px;
  margin-right: 4px;
  line-height: 16px;
}
.mi-when-label {
  background: rgba(15, 198, 194, 0.1);
  color: #0FC6C2;
}
.mi-example-label {
  background: rgba(255, 125, 0, 0.1);
  color: #FF7D00;
}
.mi-example {
  color: #3370FF;
  font-style: italic;
}
.mi-desc {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin-top: 4px;
  border-top: 1px dashed var(--color-border);
  padding-top: 6px;
}
</style>
