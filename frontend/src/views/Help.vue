<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">帮助中心</h2>
    </div>

    <div class="help-body">
      <!-- 搜索框 -->
      <div class="help-search">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索帮助内容，如：如何创建工单"
          size="large"
          clearable
          @keyup.enter="handleHelpSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <!-- 快捷入口 -->
      <div class="quick-cards">
        <div
          v-for="card in quickCards"
          :key="card.title"
          class="quick-card"
          @click="scrollToSection(card.target)"
        >
          <div class="qc-icon" :style="{ background: card.color }">
            <el-icon :size="22" color="#fff"><component :is="card.icon" /></el-icon>
          </div>
          <div class="qc-info">
            <div class="qc-title">{{ card.title }}</div>
            <div class="qc-desc">{{ card.desc }}</div>
          </div>
        </div>
      </div>

      <!-- FAQ 分类 -->
      <div class="faq-sections">
        <!-- 工单管理 -->
        <el-card shadow="never" class="faq-card" id="work-order">
          <template #header>
            <div class="faq-section-header">
              <el-icon :size="18" color="#0FC6C2"><Document /></el-icon>
              <span>工单管理</span>
            </div>
          </template>
          <el-collapse accordion>
            <template v-for="item in workOrderFAQ" :key="item.q">
              <el-collapse-item :title="item.q">
                <div class="faq-answer" v-html="item.a"></div>
              </el-collapse-item>
            </template>
          </el-collapse>
        </el-card>

        <!-- 设备与备件 -->
        <el-card shadow="never" class="faq-card" id="device">
          <template #header>
            <div class="faq-section-header">
              <el-icon :size="18" color="#3370FF"><Monitor /></el-icon>
              <span>设备与备件</span>
            </div>
          </template>
          <el-collapse accordion>
            <template v-for="item in deviceFAQ" :key="item.q">
              <el-collapse-item :title="item.q">
                <div class="faq-answer" v-html="item.a"></div>
              </el-collapse-item>
            </template>
          </el-collapse>
        </el-card>

        <!-- AI 智能助手 -->
        <el-card shadow="never" class="faq-card" id="ai">
          <template #header>
            <div class="faq-section-header">
              <el-icon :size="18" color="#FF7D00"><ChatLineSquare /></el-icon>
              <span>AI 智能助手</span>
            </div>
          </template>
          <!-- 三种 AI 模式说明 -->
          <div class="ai-mode-intro">
            <div class="ai-mode-title">AI 助手的三种模式怎么选？</div>
            <div class="ai-mode-cards">
              <div v-for="card in modeHelpCards" :key="card.name" class="ai-mode-card">
                <div class="am-card-head">
                  <div class="am-icon" :style="{ background: card.color }">
                    <el-icon :size="16" color="#fff"><component :is="card.icon" /></el-icon>
                  </div>
                  <span class="am-name">{{ card.name }}</span>
                </div>
                <div class="am-when"><span class="am-when-label">适合</span>{{ card.when }}</div>
                <div class="am-example"><span class="am-example-label">例如</span>{{ card.example }}</div>
                <div class="am-desc">{{ card.desc }}</div>
              </div>
            </div>
          </div>
          <el-collapse accordion>
            <template v-for="item in aiFAQ" :key="item.q">
              <el-collapse-item :title="item.q">
                <div class="faq-answer" v-html="item.a"></div>
              </el-collapse-item>
            </template>
          </el-collapse>
        </el-card>

        <!-- 账号与权限 -->
        <el-card shadow="never" class="faq-card" id="account">
          <template #header>
            <div class="faq-section-header">
              <el-icon :size="18" color="#722ED1"><User /></el-icon>
              <span>账号与权限</span>
            </div>
          </template>
          <el-collapse accordion>
            <template v-for="item in accountFAQ" :key="item.q">
              <el-collapse-item :title="item.q">
                <div class="faq-answer" v-html="item.a"></div>
              </el-collapse-item>
            </template>
          </el-collapse>
        </el-card>
      </div>

      <!-- 底部联系方式 -->
      <el-card shadow="never" class="contact-card">
        <template #header>
          <span class="contact-title">联系我们</span>
        </template>
        <div class="contact-grid">
          <div class="contact-item">
            <el-icon :size="20" color="#0FC6C2"><Phone /></el-icon>
            <div>
              <div class="contact-label">技术支持热线</div>
              <div class="contact-value">400-888-1234</div>
            </div>
          </div>
          <div class="contact-item">
            <el-icon :size="20" color="#0FC6C2"><Message /></el-icon>
            <div>
              <div class="contact-label">企业微信群</div>
              <div class="contact-value">维修知识管理-技术支持群</div>
            </div>
          </div>
          <div class="contact-item">
            <el-icon :size="20" color="#0FC6C2"><Clock /></el-icon>
            <div>
              <div class="contact-label">服务时间</div>
              <div class="contact-value">周一至周日 7×24 小时</div>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Search, Document, Monitor, ChatLineSquare, User, Phone, Message, Clock
} from '@element-plus/icons-vue'

const searchKeyword = ref('')

const quickCards = [
  { title: '工单管理', desc: '如何创建、编辑工单', icon: 'Document', color: '#0FC6C2', target: 'work-order' },
  { title: '设备与备件', desc: '设备监控、库存操作', icon: 'Monitor', color: '#3370FF', target: 'device' },
  { title: 'AI 助手', desc: '如何使用 AI 智能分析', icon: 'ChatLineSquare', color: '#FF7D00', target: 'ai' },
  { title: '账号权限', desc: '密码修改、钉钉绑定', icon: 'User', color: '#722ED1', target: 'account' },
]

const scrollToSection = (id) => {
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const handleHelpSearch = () => {
  if (searchKeyword.value.trim()) {
    ElMessage.info(`搜索"${searchKeyword.value}"相关帮助内容（功能开发中）`)
  }
}

const workOrderFAQ = [
  {
    q: '如何创建新的维修工单？',
    a: '进入<b>维修报表</b>页面，点击右上角<b>"新建工单"</b>按钮，按要求填写设备信息、故障描述、故障现象、诊断方案等内容，保存后即可生成工单。',
  },
  {
    q: '工单的状态流转是怎样的？',
    a: '草稿 → 维修中 → 已完成。创建时默认为<b>"草稿"</b>状态，填写核心信息后自动变为<b>"维修中"</b>，维修完成后需点击<b>"确认提交"</b>变为<b>"已完成"</b>。',
  },
  {
    q: '如何查看历史工单？',
    a: '在<b>维修报表</b>列表页面可按工单编号、故障描述、状态、设备类型、日期范围进行搜索和筛选。点击<b>"查看"</b>按钮可查看完整详情。',
  },
]

const deviceFAQ = [
  {
    q: '如何添加新设备？',
    a: '进入<b>设备监控</b>页面，点击<b>"新增设备"</b>，填写设备编码、名称、类型、位置、技术参数等信息后保存。接入外部监控系统后设备状态、故障标签会自动同步。',
  },
  {
    q: '备件库存不足怎么办？',
    a: '在工单的<b>"备件记录"</b>模块中添加备件时，若数量超过可用库存，输入框会变红警告，可点击<b>"紧急采购"</b>按钮发起申请。',
  },
  {
    q: '安全库存是什么意思？',
    a: '安全库存是为防止供应中断而设定的<b>最低库存警戒线</b>。当实际库存低于安全库存时，系统会发出预警通知，提醒及时补充。',
  },
]

// 三种 AI 模式说明（与 AI 问答页保持一致）
const modeHelpCards = [
  {
    name: '智能问答',
    icon: 'ChatLineSquare',
    color: '#0FC6C2',
    when: '单个故障、问题描述得清，想快速知道"以前怎么处理的"',
    example: '"3号注塑机锁模力不够怎么办？"',
    desc: 'AI 检索历史案例，几秒给出「问题分析 → 可能原因 → 排查方向 → 处理方案 → 预防建议」五段式回答。一次问一个故障最快。',
  },
  {
    name: '追踪维修',
    icon: 'Compass',
    color: '#FF7D00',
    when: '故障复杂、说不出原因，或新人需要老师傅手把手带着查',
    example: '"注塑机报 E3091，帮我一步步查"',
    desc: 'AI 像老师傅一样逐步引导排查：每步给出操作建议和判断标准，你反馈结果后继续下一步，直到定位原因。',
  },
  {
    name: '专家模式',
    icon: 'Tools',
    color: '#3370FF',
    when: '一台设备同时出现多个故障，想一次性问清楚',
    example: '"锁模力不够出飞边，油温65度报警，熔胶马达不转，三个一起查"',
    desc: 'AI 把复合问题拆成多个单故障，分别检索各自的历史案例、按故障分组回答，互不干扰、不串味。',
  },
]

const aiFAQ = [
  {
    q: 'AI 分析故障功能如何使用？',
    a: '在工单编辑页面的<b>"故障信息"</b>模块，填写故障描述后点击<b>"AI 分析故障"</b>按钮，AI 会根据故障现象推荐可能的故障码和原因。',
  },
  {
    q: 'AI 校验和 AI 分析有什么区别？',
    a: 'AI 分析故障：针对故障信息进行智能诊断，推荐故障码和原因。<br/>AI 校验：对整张工单的完整性、规范性和合理性进行审核，确保提交质量。',
  },
  {
    q: 'AI 问答看板怎么使用？',
    a: '进入<b>AI 问答看板</b>，有三种模式可选：<b>"问答模式"</b>适合单个故障快速查经验，<b>"追踪维修"</b>适合复杂故障一步步排查，<b>"专家模式"</b>适合多个故障一起问、分故障逐一分析。AI 会从知识库检索相关案例并给出参考建议。',
  },
]

const accountFAQ = [
  {
    q: '如何修改登录密码？',
    a: '点击右上角头像菜单 → <b>"账号安全"</b> → 在"修改密码"模块中填写旧密码和新密码即可完成修改。',
  },
  {
    q: '如何绑定钉钉账号？',
    a: '点击右上角头像菜单 → <b>"账号安全"</b> → 在"钉钉绑定"模块中填写 AppKey、AppSecret、AgentId、CorpId 等信息后点击绑定。绑定后可实现免登录和消息推送。',
  },
  {
    q: '忘记密码怎么办？',
    a: '请联系系统管理员或技术支持（400-888-1234）进行密码重置。权限管理的用户也可通过管理员账户重置。',
  },
]
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
.help-body {
  max-width: 860px;
}
.help-search {
  margin-bottom: 20px;
}

/* 快捷入口 */
.quick-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.quick-card {
  background: #fff;
  border: 1px solid #E5E6EB;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all .2s;
}
.quick-card:hover {
  border-color: #0FC6C2;
  box-shadow: 0 2px 8px rgba(15,198,194,0.1);
}
.qc-icon {
  width: 48px; height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.qc-info {
  flex: 1;
  min-width: 0;
}
.qc-title {
  font-size: 14px;
  font-weight: 600;
  color: #1D2129;
  margin-bottom: 2px;
}
.qc-desc {
  font-size: 12px;
  color: #86909C;
}

/* FAQ */
.faq-sections {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}
.faq-card {
  padding: 0;
}
.faq-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
}
.faq-answer {
  font-size: 14px;
  color: #4E5969;
  line-height: 1.8;
  padding: 4px 0;
}
.faq-answer :deep(b) {
  color: #1D2129;
}

/* 联系 */
.contact-card {
  padding: 0;
}
.contact-title {
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
}
.contact-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.contact-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.contact-label {
  font-size: 12px;
  color: #86909C;
  margin-bottom: 2px;
}
.contact-value {
  font-size: 14px;
  color: #1D2129;
  font-weight: 500;
}

/* ===== 三种 AI 模式说明 ===== */
.ai-mode-intro {
  padding: 0 16px 16px;
}
.ai-mode-title {
  font-size: 14px;
  font-weight: 600;
  color: #1D2129;
  margin-bottom: 10px;
}
.ai-mode-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.ai-mode-card {
  background: #F7F8FA;
  border: 1px solid #E5E6EB;
  border-radius: 8px;
  padding: 12px 14px;
}
.am-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.am-icon {
  width: 28px; height: 28px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.am-name {
  font-size: 14px;
  font-weight: 600;
  color: #1D2129;
}
.am-when,
.am-example {
  font-size: 12px;
  color: #4E5969;
  line-height: 1.6;
  margin-bottom: 2px;
}
.am-when-label,
.am-example-label {
  display: inline-block;
  font-size: 11px;
  padding: 0 4px;
  border-radius: 3px;
  margin-right: 4px;
  line-height: 16px;
}
.am-when-label {
  background: rgba(15, 198, 194, 0.12);
  color: #0FC6C2;
}
.am-example-label {
  background: rgba(255, 125, 0, 0.12);
  color: #FF7D00;
}
.am-example {
  color: #3370FF;
  font-style: italic;
}
.am-desc {
  font-size: 12px;
  color: #4E5969;
  line-height: 1.6;
  margin-top: 4px;
  border-top: 1px dashed #E5E6EB;
  padding-top: 6px;
}
</style>
