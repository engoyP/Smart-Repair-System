<template>
  <div class="page ai-chat-page">
    <div class="page-header">
      <h2 class="page-title">AI 知识问答</h2>
    </div>

    <!-- 对话区 -->
    <div class="chat-container" ref="chatContainer">
      <!-- 欢迎提示 -->
      <div class="welcome-screen" v-if="messages.length === 0">
        <div class="welcome-icon">
          <el-icon :size="40"><ChatLineSquare /></el-icon>
        </div>
        <h3>检修知识助手</h3>
        <p class="welcome-desc">描述设备故障现象，AI 将检索历史维修案例，提供维修方向与思路</p>
        <div class="hint-list">
          <div
            v-for="h in hints"
            :key="h"
            class="hint-item"
            @click="quickSend(h)"
          >
            <el-icon :size="16"><Search /></el-icon>
            <span>{{ h }}</span>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="message-list" v-else>
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="message-row"
          :class="msg.role"
        >
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="message user-msg">
            <div class="msg-bubble user-bubble">
              <p>{{ msg.content }}</p>
            </div>
            <div class="msg-avatar user-avatar">
              <el-avatar :size="36" icon="UserFilled" />
            </div>
          </div>

          <!-- AI 消息 -->
          <div v-else class="message ai-msg">
            <div class="msg-avatar ai-avatar">
              <div class="ai-avatar-inner">
                <el-icon :size="20" color="#fff"><ChatLineSquare /></el-icon>
              </div>
            </div>
            <div class="msg-content">
              <!-- 加载中 -->
              <div v-if="msg._loading" class="msg-bubble ai-bubble">
                <div class="thinking-dots">
                  <span class="dot"></span>
                  <span class="dot"></span>
                  <span class="dot"></span>
                </div>
                <span class="thinking-text">AI 正在检索知识库...</span>
              </div>

              <!-- AI 分析结果 -->
              <template v-else>
                <div class="msg-bubble ai-bubble">
                  <div class="ai-summary">{{ msg.summary }}</div>

                  <!-- 检索标签 -->
                  <div v-if="msg.strategies?.length || msg.rewriteCount" class="ai-meta">
                    <el-tag
                      v-for="s in msg.strategies"
                      :key="s"
                      size="small"
                      type="info"
                      effect="plain"
                    >{{ strategyLabel(s) }}</el-tag>
                    <el-tag
                      v-if="msg.rewriteCount > 0"
                      size="small"
                      type="warning"
                      effect="plain"
                    >改写 {{ msg.rewriteCount }} 次</el-tag>
                    <span class="ai-time">{{ msg.totalTime }}ms</span>
                  </div>

                  <!-- 结果计数 -->
                  <div v-if="msg.results.length" class="ai-result-count">
                    找到 <strong>{{ msg.results.length }}</strong> 条相关维修案例
                  </div>
                  <div v-else class="ai-result-count no-result">
                    未找到匹配的维修案例，建议换关键词重试
                  </div>
                </div>

                <!-- 来源卡片列表 -->
                <div v-if="msg.results.length" class="source-list">
                  <div
                    v-for="item in msg.results"
                    :key="item.knowledge_id"
                    class="source-card"
                    @click="openDetail(item)"
                  >
                    <div class="source-header">
                      <div class="source-tags">
                        <el-tag v-if="item.device_type" size="small" type="success" effect="plain">{{ item.device_type }}</el-tag>
                        <el-tag v-if="item.fault_code" size="small" type="warning" effect="plain">{{ item.fault_code }}</el-tag>
                      </div>
                      <span class="source-score">{{ (item.score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="source-title">{{ item.title }}</div>
                    <div class="source-content">{{ truncate(item.content, 120) }}</div>
                    <div class="source-footer">
                      <span class="source-method">{{ sourceLabel(item.source) }}</span>
                      <span class="source-id">#{{ item.knowledge_id }}</span>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="input-area">
      <div class="input-row">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="1"
          placeholder="描述设备故障现象，如：3号注塑机温度偏高，异常报警..."
          class="chat-input"
          @keydown.enter.prevent.exact="handleSend"
          resize="none"
        />
        <el-button
          type="primary"
          class="send-btn"
          :loading="isSearching"
          :disabled="!inputText.trim()"
          @click="handleSend"
        >
          <el-icon :size="20"><Promotion /></el-icon>
          <span>发送</span>
        </el-button>
      </div>
      <p class="input-hint">按 Enter 发送，Shift+Enter 换行</p>
    </div>

    <!-- 知识详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="detailItem?.title" width="720px" destroy-on-close>
      <template v-if="detailItem">
        <div class="detail-meta">
          <el-tag v-if="detailItem.device_type" type="success" effect="plain">{{ detailItem.device_type }}</el-tag>
          <el-tag v-if="detailItem.fault_code" type="warning" effect="plain">{{ detailItem.fault_code }}</el-tag>
          <span class="detail-score">相关度: {{ (detailItem.score * 100).toFixed(0) }}%</span>
        </div>
        <div class="detail-content">{{ detailItem.content }}</div>
        <div class="detail-tags" v-if="detailItem.fault_tags?.length">
          <template v-for="tag in detailItem.fault_tags" :key="tag">
            <el-tag size="small">{{ tag }}</el-tag>
          </template>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, ChatLineSquare, Promotion } from '@element-plus/icons-vue'
import request from '../api'

const chatContainer = ref(null)
const inputText = ref('')
const isSearching = ref(false)
const messages = ref([])
const detailVisible = ref(false)
const detailItem = ref(null)

const hints = [
  '注塑机温度偏高报警，可能是什么原因？',
  '电机运行时发出异常噪音，如何处理？',
  '3号机组振动大，之前有类似案例吗？',
  '液压系统漏油，常见维修方法',
  'CNC主轴异响，需要检查哪些部位？',
  '传送带打滑跑偏，维修步骤',
]

const strategyLabel = (s) => {
  const map = {
    vector_search: '向量检索',
    bm25_search: '关键词检索',
    conditional_query: '条件筛选',
    graph_query: '关联查询',
  }
  return map[s] || s
}

const sourceLabel = (s) => {
  const map = { vector: '语义匹配', bm25: '关键词', hybrid: '混合', agent: '智能检索' }
  return map[s] || s
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

const handleSend = async () => {
  const text = inputText.value.trim()
  if (!text || isSearching.value) return

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  await scrollToBottom()

  // 添加 AI 占位消息
  const aiMsg = {
    role: 'ai',
    _loading: true,
    summary: '',
    results: [],
    strategies: [],
    rewriteCount: 0,
    totalTime: 0,
  }
  messages.value.push(aiMsg)
  await scrollToBottom()

  isSearching.value = true

  try {
    const payload = {
      query: text,
      device_type: null,
      fault_code: null,
      top_k: 8,
      mode: 'agent',
    }
    const data = await request.post('/search/agent', payload)

    const results = data.results || []
    const totalTime = data.total_time_ms || 0
    const strategies = data.strategies_used || []
    const rewriteCount = data.rewrite_count || 0

    // 构建 AI 总结
    let summary = ''
    if (results.length === 0) {
      summary = '抱歉，知识库中暂未找到与您描述的问题直接相关的维修案例。建议您：\n\n1. 尝试使用不同的关键词重新描述\n2. 简化故障现象的描述\n3. 补充设备型号或故障码信息'
    } else {
      const deviceTypes = [...new Set(results.map(r => r.device_type).filter(Boolean))]
      const faultCodes = [...new Set(results.map(r => r.fault_code).filter(Boolean))]
      const topScore = results[0].score

      summary = `根据知识库检索，共找到 ${results.length} 条相关的维修案例。`
      if (deviceTypes.length) summary += `\n\n涉及设备类型：${deviceTypes.join('、')}`
      if (faultCodes.length) summary += `\n相关故障码：${faultCodes.join('、')}`
      summary += `\n\n最高匹配度 ${(topScore * 100).toFixed(0)}%，建议优先查看匹配度最高的案例。`
      summary += '\n\n点击下方的来源卡片可查看完整维修案例详情。'
    }

    // 更新 AI 消息
    aiMsg._loading = false
    aiMsg.summary = summary
    aiMsg.results = results
    aiMsg.strategies = strategies
    aiMsg.rewriteCount = rewriteCount
    aiMsg.totalTime = totalTime

    await scrollToBottom()
  } catch (e) {
    console.error('搜索失败:', e)
    aiMsg._loading = false
    aiMsg.summary = '抱歉，检索过程出现异常，请稍后重试。'
    aiMsg.results = []
    ElMessage.error('检索失败，请检查后端服务')
  } finally {
    isSearching.value = false
    await scrollToBottom()
  }
}

const openDetail = (item) => {
  detailItem.value = item
  detailVisible.value = true
}

const quickSend = (text) => {
  inputText.value = text
  handleSend()
}

// truncate helper
const truncate = (text, max = 120) => {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '...' : text
}
</script>

<style scoped>
/* ===== 页面布局 ===== */
.ai-chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ===== 对话容器 ===== */
.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 0 4px 16px 4px;
  scroll-behavior: smooth;
}
.chat-container::-webkit-scrollbar { width: 6px; }
.chat-container::-webkit-scrollbar-thumb { background: #ddd; border-radius: 3px; }

/* ===== 欢迎屏 ===== */
.welcome-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px 40px;
  text-align: center;
}
.welcome-icon {
  width: 72px; height: 72px;
  background: var(--el-color-primary-light-9);
  border-radius: 20px;
  display: flex; align-items: center; justify-content: center;
  color: var(--color-primary);
  margin-bottom: 16px;
}
.welcome-screen h3 {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}
.welcome-desc {
  font-size: 14px;
  color: var(--color-text-tertiary);
  max-width: 480px;
  line-height: 1.6;
  margin-bottom: 28px;
}
.hint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 520px;
  width: 100%;
}
.hint-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all .2s;
  color: var(--color-text-secondary);
  font-size: 14px;
}
.hint-item:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--el-color-primary-light-9);
}

/* ===== 消息列表 ===== */
.message-row {
  margin-bottom: 20px;
}

/* --- 用户消息 --- */
.message.user-msg {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-left: 60px;
}
.user-bubble {
  background: var(--color-primary);
  color: #fff;
  padding: 12px 18px;
  border-radius: 12px 12px 4px 12px;
  max-width: 100%;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

/* --- AI 消息 --- */
.message.ai-msg {
  display: flex;
  gap: 10px;
  padding-right: 60px;
}
.ai-avatar-inner {
  width: 36px; height: 36px;
  background: var(--color-primary);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.msg-content {
  flex: 1;
  min-width: 0;
}
.ai-bubble {
  background: #fff;
  border: 1px solid var(--color-border);
  padding: 16px 20px;
  border-radius: 12px 12px 12px 4px;
  line-height: 1.7;
}

/* 加载动画 */
.thinking-dots {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
}
.dot {
  width: 8px; height: 8px;
  background: var(--color-primary);
  border-radius: 50%;
  animation: bounce 1.2s infinite ease-in-out;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
.thinking-text {
  font-size: 13px;
  color: var(--color-text-tertiary);
}

/* AI 总结 */
.ai-summary {
  font-size: 14px;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  line-height: 1.8;
}
.ai-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-light);
}
.ai-time {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-left: auto;
}
.ai-result-count {
  margin-top: 10px;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.ai-result-count strong { color: var(--color-primary); }
.ai-result-count.no-result {
  color: var(--color-warning);
  background: #FFF3E8;
  padding: 8px 12px;
  border-radius: 6px;
}

/* ===== 来源卡片 ===== */
.source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.source-card {
  background: #FAFBFC;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all .2s;
}
.source-card:hover {
  border-color: var(--color-primary);
  background: var(--el-color-primary-light-9);
}
.source-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.source-tags { display: flex; gap: 4px; }
.source-score {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary);
  background: var(--el-color-primary-light-9);
  padding: 1px 8px;
  border-radius: 4px;
  white-space: nowrap;
}
.source-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
  line-height: 1.4;
}
.source-content {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}
.source-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}
.source-method {
  font-size: 11px;
  color: var(--color-text-tertiary);
  background: var(--el-fill-color-light);
  padding: 1px 8px;
  border-radius: 3px;
}
.source-id {
  font-size: 11px;
  color: var(--color-text-disabled);
  font-family: monospace;
}

/* ===== 底部输入区 ===== */
.input-area {
  flex-shrink: 0;
  border-top: 1px solid var(--color-border);
  background: #fff;
  padding: 12px 20px 16px;
  margin: 0 -24px -24px;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.chat-input {
  flex: 1;
}
.chat-input :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.5;
  padding: 10px 14px;
  min-height: 42px;
  max-height: 120px;
  resize: none;
}
.send-btn {
  height: 42px;
  padding: 0 20px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.send-btn.is-loading :deep(.el-icon) { margin-right: 0; }
.input-hint {
  font-size: 12px;
  color: var(--color-text-disabled);
  margin-top: 6px;
  padding-left: 2px;
}

/* ===== 详情弹窗 ===== */
.detail-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.detail-score {
  font-size: 13px;
  color: var(--color-primary);
  font-weight: 600;
}
.detail-content {
  font-size: 15px;
  line-height: 1.8;
  color: var(--color-text-primary);
  white-space: pre-wrap;
}
.detail-tags {
  margin-top: 16px;
  display: flex;
  gap: 6px;
}

/* ===== 滚动容器 ===== */
.page.ai-chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 48px);  /* viewport - topbar - page padding */
}
</style>
