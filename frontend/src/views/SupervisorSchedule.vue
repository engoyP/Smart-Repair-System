<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" circle @click="$router.back()" />
        <h2 class="page-title">排班管理</h2>
      </div>
    </div>

    <!-- 数据变更提示条（自动显示，3秒消失） -->
    <el-alert
      v-if="scheduleChangeTip"
      :title="scheduleChangeTip"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px;"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane label="📅 排班表" name="calendar">
        <el-card class="panel-card" shadow="never">
          <div class="panel-header">
            <h3 class="panel-title">
              <el-icon :size="18" color="#FF7D00"><Calendar /></el-icon>
              今日值日
              <el-tag size="small" type="info" effect="plain" style="margin-left:8px;">{{ todayStr }}</el-tag>
            </h3>
            <el-button type="primary" link @click="fetchDutyToday" :loading="dutyLoading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
          <div class="duty-shifts" v-loading="dutyLoading">
            <div class="shift-col shift-morning">
              <div class="shift-head">
                <span class="shift-dot"></span>
                <span class="shift-name">早班 MORNING</span>
                <span class="shift-time">08:00 - 16:00</span>
              </div>
              <div class="shift-body">
                <div v-if="!(dutyToday.MORNING || []).length" class="shift-empty">
                  <el-icon :size="24" color="#C9CDD4"><User /></el-icon>
                  <span>暂无排班</span>
                </div>
                <el-tag
                  v-for="u in (dutyToday.MORNING || [])"
                  :key="u.id"
                  size="large"
                  effect="light"
                  type="success"
                  class="duty-tag"
                >
                  <el-avatar :size="22" icon="UserFilled" style="margin-right:6px;" />
                  {{ u.real_name || u.name }}
                  <span class="duty-emp-id" v-if="u.employee_id">· {{ u.employee_id }}</span>
                </el-tag>
              </div>
            </div>
            <div class="shift-col shift-afternoon">
              <div class="shift-head">
                <span class="shift-dot"></span>
                <span class="shift-name">中班 AFTERNOON</span>
                <span class="shift-time">16:00 - 00:00</span>
              </div>
              <div class="shift-body">
                <div v-if="!(dutyToday.AFTERNOON || []).length" class="shift-empty">
                  <el-icon :size="24" color="#C9CDD4"><User /></el-icon>
                  <span>暂无排班</span>
                </div>
                <el-tag
                  v-for="u in (dutyToday.AFTERNOON || [])"
                  :key="u.id"
                  size="large"
                  effect="light"
                  type="warning"
                  class="duty-tag"
                >
                  <el-avatar :size="22" icon="UserFilled" style="margin-right:6px;" />
                  {{ u.real_name || u.name }}
                  <span class="duty-emp-id" v-if="u.employee_id">· {{ u.employee_id }}</span>
                </el-tag>
              </div>
            </div>
            <div class="shift-col shift-night">
              <div class="shift-head">
                <span class="shift-dot"></span>
                <span class="shift-name">晚班 NIGHT</span>
                <span class="shift-time">00:00 - 08:00</span>
              </div>
              <div class="shift-body">
                <div v-if="!(dutyToday.NIGHT || []).length" class="shift-empty">
                  <el-icon :size="24" color="#C9CDD4"><User /></el-icon>
                  <span>暂无排班</span>
                </div>
                <el-tag
                  v-for="u in (dutyToday.NIGHT || [])"
                  :key="u.id"
                  size="large"
                  effect="light"
                  type="info"
                  class="duty-tag"
                >
                  <el-avatar :size="22" icon="UserFilled" style="margin-right:6px;" />
                  {{ u.real_name || u.name }}
                  <span class="duty-emp-id" v-if="u.employee_id">· {{ u.employee_id }}</span>
                </el-tag>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 本周排班矩阵 -->
        <el-card class="panel-card matrix-card" shadow="never">
          <div class="panel-header">
            <h3 class="panel-title">
              <el-icon :size="18" color="#722ED1"><Grid /></el-icon>
              本周排班矩阵
              <el-tag v-if="weekData" size="small" type="info" effect="plain" style="margin-left:8px;">
                {{ weekData.start_date }} ~ {{ weekData.end_date }}
              </el-tag>
            </h3>
            <div class="matrix-toolbar">
              <el-date-picker
                v-model="weekStartDate"
                type="date"
                placeholder="起始日期"
                value-format="YYYY-MM-DD"
                style="width: 150px;"
                :clearable="false"
                @change="fetchWeekSchedule(weekStartDate)"
              />
              <el-button type="primary" @click="fetchWeekSchedule(weekStartDate)" :loading="weekLoading">
                <el-icon><Search /></el-icon>查询
              </el-button>
              <el-button @click="openBatchDialog">
                <el-icon><Plus /></el-icon>批量排班
              </el-button>
              <el-button @click="copyLastWeek" :loading="copying">
                <el-icon><CopyDocument /></el-icon>复制上周
              </el-button>
              <el-button link type="primary" @click="resetToThisWeek">回到本周</el-button>
            </div>
          </div>

          <div class="matrix-wrap" v-loading="weekLoading">
            <div class="matrix-grid" :style="{ gridTemplateColumns: '170px repeat(7, minmax(72px, 1fr))' }">
              <!-- 表头：左上角 + 7天 -->
              <div class="matrix-th matrix-corner">维修员</div>
              <div
                v-for="d in weekDates"
                :key="'h-' + d"
                class="matrix-th"
                :class="{ 'is-today': d === today }"
              >
                <div class="th-date">{{ d.slice(5) }}</div>
                <div class="th-weekday">{{ weekdayText(d) }}</div>
              </div>
              <!-- 数据行：每个维修员一行 -->
              <template v-for="user in weekUsers" :key="'r-' + user.user_id">
                <div class="matrix-row-head">
                  <el-avatar :size="26" icon="UserFilled" />
                  <div class="rh-info">
                    <div class="rh-name">{{ user.real_name }}</div>
                    <div class="rh-emp" v-if="user.employee_id">{{ user.employee_id }}</div>
                  </div>
                </div>
                <div
                  v-for="d in weekDates"
                  :key="'c-' + user.user_id + '-' + d"
                  class="matrix-cell"
                  :class="cellClass(user, d)"
                  @click="onCellClick(user, d, $event)"
                >
                  <template v-if="cellTags(user, d).length">
                    <el-tag
                      v-for="tag in cellTags(user, d)"
                      :key="tag.key"
                      :color="tag.color"
                      effect="dark"
                      size="small"
                      round
                      class="cell-tag"
                    >
                      {{ tag.text }}
                    </el-tag>
                  </template>
                  <span v-else class="cell-rest">休</span>
                </div>
              </template>
            </div>
            <div v-if="!weekUsers.length && !weekLoading" class="matrix-empty">
              <el-text type="info">暂无维修员排班数据，请使用"批量排班"或"复制上周"生成。</el-text>
            </div>
          </div>
        </el-card>

        <!-- 批量排班对话框 -->
        <el-dialog v-model="batchDialog.visible" title="批量排班" width="520px">
          <el-form :model="batchForm" label-width="90px">
            <el-form-item label="班次">
              <el-radio-group v-model="batchForm.shift">
                <el-radio-button value="MORNING"><span style="color:#00B42A;">早班</span></el-radio-button>
                <el-radio-button value="AFTERNOON"><span style="color:#FF7D00;">中班</span></el-radio-button>
                <el-radio-button value="NIGHT"><span style="color:#722ED1;">晚班</span></el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="排班类型">
              <el-select v-model="batchForm.schedule_type" style="width: 200px;">
                <el-option label="手动排班" value="MANUAL" />
                <el-option label="常规排班" value="WEEKLY_ROUTINE" />
              </el-select>
            </el-form-item>
            <el-form-item label="维修员">
              <el-select
                v-model="batchForm.user_ids"
                multiple
                filterable
                placeholder="选择多个维修员"
                style="width: 100%;"
                collapse-tags
                collapse-tags-tooltip
              >
                <el-option
                  v-for="t in technicians"
                  :key="t.id"
                  :label="`${t.real_name || t.name} (${t.employee_id || t.id})`"
                  :value="t.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="日期范围">
              <el-date-picker
                v-model="batchForm.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                value-format="YYYY-MM-DD"
                style="width: 100%;"
              />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="batchDialog.visible = false">取消</el-button>
            <el-button type="primary" @click="submitBatch" :loading="batchLoading">确定排班</el-button>
          </template>
        </el-dialog>

        <!-- 单元格编辑浮动菜单 -->
        <teleport to="body">
          <div v-if="cellMenu.visible" class="cell-menu-backdrop" @click="closeCellMenu"></div>
          <div
            v-if="cellMenu.visible"
            class="cell-menu"
            :style="{ left: cellMenu.x + 'px', top: cellMenu.y + 'px' }"
            @click.stop
          >
            <div class="cell-menu-title">设置班次</div>
            <button class="cell-menu-item" @click="setCellShift('MORNING')">
              <span class="dot dot-morning"></span>早班
            </button>
            <button class="cell-menu-item" @click="setCellShift('AFTERNOON')">
              <span class="dot dot-afternoon"></span>中班
            </button>
            <button class="cell-menu-item" @click="setCellShift('NIGHT')">
              <span class="dot dot-night"></span>晚班
            </button>
            <div class="cell-menu-divider"></div>
            <button class="cell-menu-item danger" @click="clearCellShift">
              <el-icon><Delete /></el-icon>清除
            </button>
          </div>
        </teleport>

        <div class="form-row">
          <el-card class="panel-card form-card" shadow="never">
            <div class="panel-header">
              <h3 class="panel-title">
                <el-icon :size="18" color="#3491FA"><Edit /></el-icon>
                排班创建（单日单班次批量）
              </h3>
            </div>
            <el-form
              :model="form"
              ref="formRef"
              label-width="90px"
              :rules="rules"
              class="duty-form"
            >
              <el-form-item label="排班日期" prop="date">
                <el-date-picker
                  v-model="form.date"
                  type="date"
                  placeholder="选择日期"
                  value-format="YYYY-MM-DD"
                  style="width: 240px;"
                />
              </el-form-item>
              <el-form-item label="班制" prop="shift">
                <el-radio-group v-model="form.shift">
                  <el-radio-button label="MORNING" value="MORNING">
                    <span style="color:#00B42A;">早班</span>
                  </el-radio-button>
                  <el-radio-button label="AFTERNOON" value="AFTERNOON">
                    <span style="color:#FF7D00;">中班</span>
                  </el-radio-button>
                  <el-radio-button label="NIGHT" value="NIGHT">
                    <span style="color:#722ED1;">晚班</span>
                  </el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="维修员" prop="technician_ids">
                <el-select
                  v-model="form.technician_ids"
                  multiple
                  filterable
                  placeholder="选择多个维修员"
                  style="width: 100%; min-width: 360px;"
                  collapse-tags
                  collapse-tags-tooltip
                >
                  <el-option
                    v-for="t in technicians"
                    :key="t.id"
                    :label="`${t.real_name || t.name} (${t.employee_id || t.id})`"
                    :value="t.id"
                  >
                    <el-avatar :size="20" icon="UserFilled" style="margin-right:6px;" />
                    {{ t.real_name || t.name }}
                    <span style="color:#86909C; margin-left:6px;">{{ t.employee_id || t.id }}</span>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="备注">
                <el-input
                  v-model="form.remark"
                  placeholder="可选，如节假日说明等"
                  style="max-width: 360px;"
                  maxlength="100"
                  show-word-limit
                />
              </el-form-item>
              <el-form-item>
                <el-button
                  type="primary"
                  size="large"
                  @click="handleCreateBatch"
                  :loading="creating"
                >
                  <el-icon style="margin-right:6px;"><Check /></el-icon>
                  提交排班
                </el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="📋 请假审批" name="approval">
        <!-- 查询区 -->
        <el-card shadow="never" style="margin-bottom: 12px;">
          <el-form :inline="true" :model="approvalQuery" label-width="80px" size="default">
            <el-form-item label="状态">
              <el-select v-model="approvalQuery.status" placeholder="全部" clearable style="width: 150px;" @change="loadApprovalList(1)">
                <el-option label="待审批" value="PENDING" />
                <el-option label="已批准" value="APPROVED" />
                <el-option label="已拒绝" value="REJECTED" />
                <el-option label="已撤销" value="CANCELLED" />
              </el-select>
            </el-form-item>
            <el-form-item label="假别">
              <el-select v-model="approvalQuery.leave_type" placeholder="全部" clearable style="width: 130px;" @change="loadApprovalList(1)">
                <el-option label="年假" value="ANNUAL" />
                <el-option label="病假" value="SICK" />
                <el-option label="事假" value="PERSONAL" />
                <el-option label="调休" value="COMPENSATION" />
                <el-option label="其他" value="OTHER" />
              </el-select>
            </el-form-item>
            <el-form-item label="日期范围">
              <el-date-picker
                v-model="approvalQuery.dateRange"
                type="daterange"
                start-placeholder="起始"
                end-placeholder="结束"
                value-format="YYYY-MM-DD"
                style="width: 260px;"
                @change="loadApprovalList(1)"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Refresh" @click="loadApprovalList(1)">刷新</el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 列表 -->
        <el-card shadow="never">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span>请假申请审批（共 {{approvalTotal}} 条）</span>
              <el-tag v-if="pendingCount>0" type="danger" effect="dark">⏳ 待审批 {{pendingCount}} 条</el-tag>
            </div>
          </template>

          <el-table
            :data="approvalList"
            v-loading="approvalLoading"
            border
            stripe
            style="width: 100%"
            @row-click="showLeaveDetail"
            highlight-current-row
          >
            <el-table-column label="ID" width="70" prop="id" />
            <el-table-column label="申请人" width="110" prop="requester_name" />
            <el-table-column label="假别" width="90">
              <template #default="{ row }">
                <el-tag :type="leaveTypeTag(row.leave_type)">{{ leaveTypeText(row.leave_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="请假时段" width="300">
              <template #default="{ row }">
                <div v-if="row.details && row.details.length">
                  <div v-for="(d, idx) in row.details.slice(0, 2)" :key="d.id">
                    <span style="font-family: monospace;">{{ formatDate(d.leave_date) }}</span>
                    <el-tag size="small" style="margin-left:6px;">{{ shiftText(d.leave_shift) }}</el-tag>
                  </div>
                  <small v-if="row.details.length > 2" style="color:#86909C;">共 {{row.details.length}} 天…</small>
                </div>
                <span v-else style="color:#c9cdd4;">-</span>
              </template>
            </el-table-column>
            <el-table-column label="理由" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.leave_reason || '（无）' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="leaveStatusTag(row.status)" effect="light">{{ leaveStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="210" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.status === 'PENDING'"
                  type="success"
                  size="small"
                  @click.stop="openApprove(row)"
                >批准</el-button>
                <el-button
                  v-if="row.status === 'PENDING'"
                  type="danger"
                  size="small"
                  @click.stop="openReject(row)"
                >拒绝</el-button>
                <el-button size="small" @click.stop="showLeaveDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="margin-top: 16px; text-align: right;">
            <el-pagination
              background
              layout="total, prev, pager, next, sizes"
              :total="approvalTotal"
              :page-size="approvalQuery.page_size"
              :page-sizes="[10, 20, 50, 100]"
              :current-page="approvalQuery.page"
              @current-change="loadApprovalList"
              @size-change="(sz) => { approvalQuery.page_size = sz; loadApprovalList(1); }"
            />
          </div>
        </el-card>

        <!-- 详情/审批弹窗 -->
        <el-dialog
          v-model="detailVisible"
          :title="`请假申请 #${currentLeave.id || ''} 详情`"
          width="760px"
          :close-on-click-modal="false"
          destroy-on-close
        >
          <div v-if="currentLeave.id">
            <el-descriptions :column="2" border size="small" style="margin-bottom: 12px;">
              <el-descriptions-item label="申请人">{{ currentLeave.requester_name }}</el-descriptions-item>
              <el-descriptions-item label="申请编号">
                <span style="font-family: monospace;">{{ currentLeave.correlation_id || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="假别">
                <el-tag :type="leaveTypeTag(currentLeave.leave_type)">{{ leaveTypeText(currentLeave.leave_type) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="leaveStatusTag(currentLeave.status)" effect="light">{{ leaveStatusText(currentLeave.status) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="请假理由" :span="2">{{ currentLeave.leave_reason || '（无）' }}</el-descriptions-item>
              <el-descriptions-item label="提交时间" :span="2">{{ formatDateTime(currentLeave.submitted_at) }}</el-descriptions-item>
            </el-descriptions>

            <h4 style="margin: 6px 0 10px; color:#1D2129;">📆 请假时段明细（{{ currentLeave.details ? currentLeave.details.length : 0 }} 条）</h4>
            <el-table :data="currentLeave.details" border size="small" style="margin-bottom: 12px;">
              <el-table-column label="日期" width="140">
                <template #default="{ row }">{{ formatDate(row.leave_date) }}</template>
              </el-table-column>
              <el-table-column label="班次" width="120">
                <template #default="{ row }">
                  <el-tag size="small">{{ shiftText(row.leave_shift) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="审批后剩余值班人数" min-width="140">
                <template #default="{ row }">
                  <span v-if="currentLeave.on_duty_after && currentLeave.on_duty_after[row.leave_date] !== undefined">
                    <el-tag :type="(+currentLeave.on_duty_after[row.leave_date]) < 2 ? 'danger' : 'success'">
                      剩余 {{ currentLeave.on_duty_after[row.leave_date] }} 人
                    </el-tag>
                  </span>
                  <span v-else style="color:#C9CDD4;">-</span>
                </template>
              </el-table-column>
            </el-table>

            <!-- 冲突工单警告 -->
            <div v-if="currentLeave.pending_work_orders && currentLeave.pending_work_orders.length"
                 style="margin-bottom: 12px; padding: 10px 14px; background:#FFF2EC; border:1px solid #FFE0C2; border-radius: 6px;">
              <div style="font-weight:600; color:#F53F3F; margin-bottom: 6px;">
                ⚠️ 存在未完成工单冲突（{{ currentLeave.pending_work_orders.length }} 条），请先转派工单再审批
              </div>
              <ul style="margin: 0; padding-left: 18px; color:#86909C; font-size: 13px;">
                <li v-for="w in currentLeave.pending_work_orders" :key="w.work_order_id" style="margin:2px 0;">
                  #{{ w.work_order_no }} - [{{ w.status }}] {{ w.fault_description }}
                  <small v-if="w.start_time" style="color:#C9CDD4;">(开始: {{ w.start_time.slice(0,16).replace('T',' ') }})</small>
                </li>
              </ul>
            </div>

            <!-- 人数不足警告 + 顶岗人选择器 -->
            <div v-if="approvalNeedSubstitute"
                 style="margin-bottom: 12px; padding: 10px 14px; background:#F53F3F15; border:1px solid #F53F3F55; border-radius: 6px;">
              <div style="font-weight:600; color:#F53F3F; margin-bottom: 8px;">
                🔴 在岗人数将低于最低值班人数（{{ currentMinGuard }} 人），必须指定顶岗人才能批准
              </div>
              <el-form :model="approveForm" label-width="100px" size="default">
                <el-form-item label="指定顶岗人" required>
                  <el-select
                    v-model="approveForm.substitute_user_id"
                    placeholder="请选择当天在岗的维修师傅来顶替"
                    filterable
                    style="width: 420px;"
                  >
                    <el-option
                      v-for="u in substituteCandidates"
                      :key="u.id"
                      :label="`${u.real_name || u.username} (工号:${u.employee_id || u.id})`"
                      :value="u.id"
                    />
                  </el-select>
                </el-form-item>
              </el-form>
            </div>

            <el-form :model="approveForm" label-width="80px" size="default">
              <el-form-item label="审批备注">
                <el-input
                  v-model="approveForm.approver_comment"
                  type="textarea"
                  :rows="2"
                  maxlength="500"
                  show-word-limit
                  placeholder="同意/拒绝的理由（拒绝必填）"
                />
              </el-form-item>
            </el-form>
          </div>
          <template #footer>
            <el-button @click="detailVisible = false">关闭</el-button>
            <el-button
              v-if="currentLeave.status === 'PENDING'"
              type="danger"
              @click="confirmReject"
              :disabled="!!(actionBusy)"
            >拒绝</el-button>
            <el-button
              v-if="currentLeave.status === 'PENDING'"
              type="success"
              :loading="actionBusy"
              :disabled="approvalNeedSubstitute && !approveForm.substitute_user_id"
              @click="confirmApprove"
            >批准请假</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft, Calendar, Refresh, Edit, Check, User,
  Grid, Search, Plus, CopyDocument, Delete, Bell
} from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import request from '../api'
import {
  listDutyToday,
  createDutyBatch,
  listTechnicians,
  // Phase 2.1 新增：
  leaveList,
  leaveDetail,
  leaveApprove,
  leaveReject,
  leavePreCheck,
} from '../api/supervisor'

const formRef = ref(null)
const dutyLoading = ref(false)
const creating = ref(false)

const todayStr = computed(() => dayjs().format('YYYY年MM月DD日 dddd'))

const form = reactive({
  date: dayjs().format('YYYY-MM-DD'),
  shift: 'MORNING',
  technician_ids: [],
  remark: '',
})

const rules = {
  date: [{ required: true, message: '请选择日期', trigger: 'change' }],
  shift: [{ required: true, message: '请选择班制', trigger: 'change' }],
  technician_ids: [
    { required: true, type: 'array', min: 1, message: '请至少选择一个维修员', trigger: 'change' }
  ],
}

const dutyToday = reactive({
  MORNING: [],
  AFTERNOON: [],
  NIGHT: [],
})

const technicians = ref([])

const fetchDutyToday = async () => {
  dutyLoading.value = true
  try {
    const res = await listDutyToday()
    const data = Array.isArray(res) ? res : (res.items || res || [])
    dutyToday.MORNING = []
    dutyToday.AFTERNOON = []
    dutyToday.NIGHT = []
    data.forEach(d => {
      const key = d.shift || d.shift_type
      const user = d.user || d.technician || d
      if (key === 'MORNING') dutyToday.MORNING.push(user)
      else if (key === 'AFTERNOON') dutyToday.AFTERNOON.push(user)
      else if (key === 'NIGHT') dutyToday.NIGHT.push(user)
    })
  } catch {
  } finally {
    dutyLoading.value = false
  }
}

const fetchTechnicians = async () => {
  try {
    const res = await listTechnicians()
    technicians.value = Array.isArray(res) ? res : (res.items || [])
  } catch {
    technicians.value = []
  }
}

const handleCreateBatch = async () => {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    const payload = {
      schedules: [
        {
          date: form.date,
          shift: form.shift,
          technician_ids: [...form.technician_ids],
          remark: form.remark || undefined,
        }
      ]
    }
    await createDutyBatch(payload)
    ElMessage.success('排班创建成功')
    form.technician_ids = []
    form.remark = ''
    await fetchDutyToday()
    await fetchWeekSchedule(weekStartDate.value)
  } catch {
  } finally {
    creating.value = false
  }
}

const activeTab = ref('calendar')

const today = dayjs().format('YYYY-MM-DD')

const shiftText = (s) => {
  const map = {
    MORNING: '早班',
    AFTERNOON: '中班',
    NIGHT: '晚班',
    ALL_DAY: '全天',
  }
  return map[s] || s || '-'
}

const leaveTypeText = (t) => {
  const map = {
    ANNUAL: '年假',
    SICK: '病假',
    PERSONAL: '事假',
    COMPENSATION: '调休',
    OTHER: '其他',
  }
  return map[t] || t || '-'
}

// ==================== 排班矩阵 ====================

// 获取本周一日期（ISO 周一为起始）
function getThisMonday() {
  const t = dayjs()
  const dow = t.day() // 0=周日, 1=周一
  const diff = dow === 0 ? -6 : (1 - dow)
  return t.add(diff, 'day').format('YYYY-MM-DD')
}

const weekLoading = ref(false)
const weekStartDate = ref(getThisMonday())
const weekData = ref(null)
const copying = ref(false)

// 本周7天日期列表（未加载时以选中起始日期推算）
const weekDates = computed(() => {
  const start = weekData.value?.start_date || weekStartDate.value
  return Array.from({ length: 7 }, (_, i) => dayjs(start).add(i, 'day').format('YYYY-MM-DD'))
})

// 矩阵中的维修员列表（来自周排班接口）
const weekUsers = computed(() => weekData.value?.users || [])

// 查询周排班
const fetchWeekSchedule = async (startDate) => {
  if (!startDate) return
  weekLoading.value = true
  try {
    const res = await request.get('/duty-schedules/week', { params: { start_date: startDate } })
    weekData.value = res
  } catch {
    weekData.value = null
  } finally {
    weekLoading.value = false
  }
}

// 回到本周
const resetToThisWeek = () => {
  weekStartDate.value = getThisMonday()
  fetchWeekSchedule(weekStartDate.value)
}

// 获取单元格数据
const getCell = (user, date) => user.days?.[date]

// 班次标签文字（早绿/中橙/晚紫/请假红，与今日值日配色一致）
const shiftLabel = (s) => ({ MORNING: '早', AFTERNOON: '中', NIGHT: '晚' }[s] || s)
const shiftColor = (s) => ({ MORNING: '#00B42A', AFTERNOON: '#FF7D00', NIGHT: '#722ED1' }[s] || '#86909C')

// 单元格标签数组：支持一人同天多班次（逗号拼接/数组）并列显示，可叠加请假标签
const cellTags = (user, date) => {
  const cell = getCell(user, date)
  if (!cell) return []
  const tags = []
  // 请假标签（全天/半天请假）
  const leave = cell.leave_info || (cell.schedule_type === 'LEAVE' ? { shift: cell.shift } : null)
  if (leave) {
    const lvShift = leave.shift || 'ALL_DAY'
    const text = lvShift === 'ALL_DAY' ? '请假中' : ('请假' + shiftLabel(lvShift))
    tags.push({ key: 'leave', text, color: '#F53F3F' })
  }
  // 正常班次：后端可能返回逗号拼接字符串或含 id 的数组
  let shifts = []
  if (Array.isArray(cell.shifts)) {
    shifts = cell.shifts.map(s => s.shift)
  } else if (cell.shift && cell.schedule_type !== 'LEAVE') {
    shifts = String(cell.shift).split(',')
  }
  shifts.filter(Boolean).forEach(s => {
    tags.push({ key: 's-' + s, text: shiftLabel(s), color: shiftColor(s) })
  })
  return tags
}

// 单元格当天该用户的所有班次记录（含 id，供清除使用）
const getCellShifts = (user, date) => {
  const cell = getCell(user, date)
  if (cell && Array.isArray(cell.shifts)) return cell.shifts
  if (!cell) return []
  return cell.shift ? [{ id: cell.id || null, shift: cell.shift }] : []
}

// 单元格 CSS class（全天请假 → 灰色背景）
const cellClass = (user, date) => {
  const cell = getCell(user, date)
  if (!cell) return 'cell-empty'
  if (cell.schedule_type === 'LEAVE' && (cell.shift === 'ALL_DAY' || cell.shift === null)) return 'cell-leave-fullday'
  return ''
}

// 日期转星期文字
const weekdayText = (date) => {
  const map = ['日', '一', '二', '三', '四', '五', '六']
  return '周' + map[dayjs(date).day()]
}

// ----- 单元格编辑菜单 -----
const cellMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  user: null,
  date: '',
  cell: null,
  cells: []  // 当天该用户的所有班次记录 [{id, shift}]
})

// 点击单元格 → 打开编辑菜单（请假单元格拦截）
const onCellClick = (user, date, event) => {
  const cell = getCell(user, date)
  if (cell && cell.schedule_type === 'LEAVE' && !cell.shifts?.length) {
    ElMessage.warning('该日期已请假，不可排班')
    return
  }
  const rect = event.currentTarget.getBoundingClientRect()
  cellMenu.visible = true
  cellMenu.x = rect.right + 4
  cellMenu.y = rect.top
  cellMenu.user = user
  cellMenu.date = date
  cellMenu.cell = cell
  cellMenu.cells = getCellShifts(user, date)
}

const closeCellMenu = () => {
  cellMenu.visible = false
}

// 设置单元格班次（单用户单日）
const setCellShift = async (shift) => {
  const { user, date } = cellMenu
  closeCellMenu()
  try {
    await request.post('/duty-schedules/', {
      date_from: date,
      date_to: date,
      items: [{ shift, user_ids: [user.user_id], schedule_type: 'MANUAL' }]
    })
    ElMessage.success('排班已更新')
    await fetchWeekSchedule(weekStartDate.value)
  } catch {
    // 错误已由拦截器处理
  }
}

// 清除单元格班次（当天该用户的所有班次并列删除）
const clearCellShift = async () => {
  const { user, date, cells } = cellMenu
  closeCellMenu()
  const records = cells || []
  if (!records.length) {
    ElMessage.warning('该单元格无排班记录')
    return
  }
  try {
    for (const r of records) {
      if (r.id) {
        await request.delete(`/duty-schedules/${r.id}`)
      } else {
        // 无 id 时按 user + date + shift 查询清除
        await request.delete('/duty-schedules', {
          params: { user_id: user.user_id, date, shift: r.shift }
        })
      }
    }
    ElMessage.success('已清除')
    await fetchWeekSchedule(weekStartDate.value)
  } catch {
    // 错误已由拦截器处理
  }
}

// ----- 批量排班对话框 -----
const batchDialog = reactive({ visible: false })
const batchLoading = ref(false)
const batchForm = reactive({
  shift: 'MORNING',
  schedule_type: 'MANUAL',
  user_ids: [],
  dateRange: [today, today]
})

const openBatchDialog = () => {
  // 默认日期范围设为当前查询周
  batchForm.dateRange = [weekStartDate.value, dayjs(weekStartDate.value).add(6, 'day').format('YYYY-MM-DD')]
  batchDialog.visible = true
}

// 提交批量排班（400 冲突 → 显示详情列表）
const submitBatch = async () => {
  if (!batchForm.user_ids.length) {
    ElMessage.warning('请选择维修员')
    return
  }
  if (!batchForm.dateRange || batchForm.dateRange.length !== 2) {
    ElMessage.warning('请选择日期范围')
    return
  }
  batchLoading.value = true
  try {
    await request.post('/duty-schedules/', {
      date_from: batchForm.dateRange[0],
      date_to: batchForm.dateRange[1],
      items: [{
        shift: batchForm.shift,
        user_ids: [...batchForm.user_ids],
        schedule_type: batchForm.schedule_type
      }]
    })
    ElMessage.success('批量排班成功')
    batchDialog.visible = false
    await fetchWeekSchedule(weekStartDate.value)
  } catch (e) {
    // 400 冲突 → 展示冲突详情
    if (e?.response?.status === 400) {
      const detail = e.response.data?.detail
      let lines = []
      if (Array.isArray(detail)) {
        lines = detail.map(d => {
          const date = d.date || d.schedule_date || ''
          const name = d.real_name || d.user_name || d.user_id || ''
          const reason = d.reason || d.message || JSON.stringify(d)
          return `${date} ${name}：${reason}`
        })
      } else if (typeof detail === 'string') {
        lines = [detail]
      } else if (detail && typeof detail === 'object') {
        lines = [JSON.stringify(detail)]
      }
      if (lines.length) {
        ElMessageBox.alert(
          lines.join('<br/>'),
          '排班冲突详情',
          { type: 'error', dangerouslyUseHTMLString: true }
        )
      }
    }
    // 其他错误已由拦截器统一提示
  } finally {
    batchLoading.value = false
  }
}

// ----- 复制上周排班 -----
const copyLastWeek = async () => {
  const targetStart = weekStartDate.value
  const sourceStart = dayjs(targetStart).subtract(7, 'day').format('YYYY-MM-DD')
  try {
    await ElMessageBox.confirm(
      `将上周（${sourceStart} 起）排班复制到本周（${targetStart} 起）？`,
      '复制上周排班',
      { type: 'info', confirmButtonText: '复制', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  copying.value = true
  try {
    const res = await request.post('/duty-schedules/copy-week', {
      source_start_date: sourceStart,
      target_start_date: targetStart
    })
    // 显示结果，包含跳过的记录
    const skipped = res?.skipped || res?.skipped_records || []
    const copied = res?.copied ?? res?.created ?? res?.count ?? 0
    if (skipped.length) {
      const lines = skipped.map(s => {
        const date = s.date || s.schedule_date || ''
        const name = s.real_name || s.user_name || s.user_id || ''
        const reason = s.reason || s.message || ''
        return `${date} ${name}：${reason}`
      })
      ElMessageBox.alert(
        `成功复制 ${copied} 条，跳过 ${skipped.length} 条：<br/>${lines.join('<br/>')}`,
        '复制结果',
        { type: 'warning', dangerouslyUseHTMLString: true }
      )
    } else {
      ElMessage.success(`复制成功，共 ${copied} 条`)
    }
    await fetchWeekSchedule(weekStartDate.value)
  } catch {
    // 错误已由拦截器处理
  } finally {
    copying.value = false
  }
}

// ================================================================
// Phase 2.1: Tab3 请假审批页
// ================================================================

const approvalQuery = reactive({
  page: 1,
  page_size: 20,
  status: 'PENDING',
  leave_type: '',
  dateRange: null,
})
const approvalList = ref([])
const approvalTotal = ref(0)
const approvalLoading = ref(false)
const pendingCount = ref(0)

const detailVisible = ref(false)
const currentLeave = reactive({})
const actionBusy = ref(false)
const approveForm = reactive({
  substitute_user_id: null,
  approver_comment: '',
})
const approvalNeedSubstitute = ref(false)
const currentMinGuard = ref(2)
const substituteCandidates = ref([])

// 轮询：每 30 秒刷新一次待审批数量和列表（若在审批Tab则刷新列表，否则只刷新右上角计数）
let _pollTimer = null
const startPoll = () => {
  stopPoll()
  _pollTimer = setInterval(() => {
    if (activeTab.value === 'approval') {
      loadApprovalList(approvalQuery.page, true)
    } else {
      loadPendingCountOnly()
    }
  }, 30000)
}
const stopPoll = () => {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
}

// 排班变更提示：记录最近一次排班哈希值（简单用 history 总条数做信号）
let _lastDutyTotal = -1
let _lastLeaveTotal = -1
const scheduleChangeTip = ref('')
const _dutyTipDismissed = ref(false)

const detectScheduleChange = async () => {
  try {
    // 只在 approval 或 calendar tab 检测
    const params = { page: 1, page_size: 1, status: approvalQuery.status || undefined }
    if (approvalQuery.leave_type) params.leave_type = approvalQuery.leave_type
    const res = await leaveList(params)
    const curTotal = res.total ?? 0
    if (_lastLeaveTotal !== -1 && curTotal !== _lastLeaveTotal) {
      scheduleChangeTip.value = `💡 请假列表有新变更（${curTotal > _lastLeaveTotal ? '新增了请假申请' : '数据已更新'}），页面已自动刷新`
      _dutyTipDismissed.value = false
      // 3 秒后自动消失
      setTimeout(() => { scheduleChangeTip.value = '' }, 3000)
    }
    _lastLeaveTotal = curTotal
    pendingCount.value = curTotal
  } catch {}
}

const loadPendingCountOnly = async () => {
  try {
    const r = await leaveList({ page: 1, page_size: 1, status: 'PENDING' })
    pendingCount.value = r.total ?? 0
  } catch {}
}

const loadApprovalList = async (page = 1, silent = false) => {
  approvalQuery.page = page
  approvalLoading.value = !silent ? true : approvalLoading.value
  try {
    const params = {
      page: approvalQuery.page,
      page_size: approvalQuery.page_size,
    }
    if (approvalQuery.status) params.status = approvalQuery.status
    if (approvalQuery.leave_type) params.leave_type = approvalQuery.leave_type
    if (approvalQuery.dateRange && approvalQuery.dateRange.length === 2) {
      params.from = approvalQuery.dateRange[0]
      params.to = approvalQuery.dateRange[1]
    }
    const res = await leaveList(params)
    approvalList.value = res.items || []
    approvalTotal.value = res.total ?? 0
    // 同步 pending 计数（如果当前过滤条件恰好是 PENDING，用 total，否则单独拉一次 PENDING）
    if (approvalQuery.status === 'PENDING') {
      pendingCount.value = approvalTotal.value
    } else {
      loadPendingCountOnly()
    }
    detectScheduleChange()
  } catch {
  } finally {
    approvalLoading.value = false
  }
}

// ---------------- 文本 / 枚举辅助（Tab2已有 leaveTypeText/shiftText，这里补 Tag 和状态辅助） ----------------
const leaveTypeTag = (t) => ({
  ANNUAL: '', SICK: 'danger', PERSONAL: 'warning', COMPENSATION: 'success',
  MARRIAGE: 'info', MATERNITY: '', FUNERAL: 'info', OTHER: 'info',
}[t] || 'info')

const leaveStatusText = (s) => ({
  PENDING: '待审批', APPROVED: '已批准', REJECTED: '已拒绝', CANCELLED: '已撤销',
}[s] || s || '-')
const leaveStatusTag = (s) => ({
  PENDING: 'warning', APPROVED: 'success', REJECTED: 'danger', CANCELLED: 'info',
}[s] || 'info')

const formatDate = (d) => d ? dayjs(d).format('YYYY-MM-DD ddd') : '-'
const formatDateTime = (d) => d ? dayjs(d).format('YYYY-MM-DD HH:mm') : '-'

// ---------------- 详情 + 批准/拒绝 ----------------
const showLeaveDetail = async (row) => {
  if (!row || !row.id) return
  try {
    const res = await leaveDetail(row.id)
    Object.keys(currentLeave).forEach(k => delete currentLeave[k])
    Object.assign(currentLeave, res || {})
    currentMinGuard.value = 2
    approvalNeedSubstitute.value = false
    substituteCandidates.value = []
    approveForm.substitute_user_id = null
    approveForm.approver_comment = currentLeave.approver_comment || ''
    try {
      const details = (currentLeave.details || []).map((d) => ({
        leave_date: typeof d.leave_date === 'string' ? d.leave_date : dayjs(d.leave_date).format('YYYY-MM-DD'),
        leave_shift: d.leave_shift,
      }))
      const pc = await leavePreCheck({
        requester_id: currentLeave.requester_id,
        details: JSON.stringify(details),
      })
      approvalNeedSubstitute.value = !!pc.need_substitute
      currentMinGuard.value = pc.min_guard_count || 2
      if (pc.need_substitute) {
        const r2 = await listTechnicians()
        substituteCandidates.value = (Array.isArray(r2) ? r2 : (r2.items || [])).filter(
          (u) => u.id !== currentLeave.requester_id && u.is_active !== false,
        )
      }
    } catch (e) {}
    detailVisible.value = true
  } catch {}
}

const openApprove = (row) => showLeaveDetail(row)
const openReject = (row) => showLeaveDetail(row)

const confirmReject = async () => {
  if (!approveForm.approver_comment || approveForm.approver_comment.trim().length < 2) {
    ElMessage.warning('拒绝理由必填（至少 2 个字符）')
    return
  }
  try {
    actionBusy.value = true
    await leaveReject(currentLeave.id, { approver_comment: approveForm.approver_comment })
    ElMessage.success('已拒绝请假申请')
    detailVisible.value = false
    loadApprovalList(approvalQuery.page)
  } finally {
    actionBusy.value = false
  }
}

const confirmApprove = async () => {
  if (approvalNeedSubstitute.value && !approveForm.substitute_user_id) {
    ElMessage.warning('在岗人数不足，请指定顶岗人再批准')
    return
  }
  try {
    actionBusy.value = true
    await leaveApprove(currentLeave.id, {
      substitute_user_id: approveForm.substitute_user_id || undefined,
      approver_comment: approveForm.approver_comment || undefined,
    })
    ElMessage.success('已批准请假，排班表已自动同步')
    detailVisible.value = false
    loadApprovalList(approvalQuery.page)
    // 同时刷新排班矩阵和今日值日（排班已变更）
    fetchWeekSchedule(weekStartDate.value)
    fetchDutyToday()
  } finally {
    actionBusy.value = false
  }
}

// Tab 切换时启动加载
watch(activeTab, (newVal) => {
  if (newVal === 'approval') {
    loadApprovalList(1)
  }
})

onBeforeUnmount(() => { stopPoll() })

onMounted(() => {
  fetchDutyToday()
  fetchTechnicians()
  // 自动加载本周排班矩阵
  fetchWeekSchedule(weekStartDate.value)
  // 初始加载待审批计数
  loadPendingCountOnly()
  // 启动轮询（30秒刷新）
  startPoll()
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

.panel-card {
  margin-bottom: 16px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #1D2129;
  display: flex;
  align-items: center;
  gap: 6px;
}

.duty-shifts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.shift-col {
  background: #F7F8FA;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #F2F3F5;
}
.shift-morning { border-top: 3px solid #00B42A; }
.shift-afternoon { border-top: 3px solid #FF7D00; }
.shift-night { border-top: 3px solid #722ED1; }

.shift-head {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px dashed #E5E6EB;
}
.shift-morning .shift-head { background: #F6FFED; }
.shift-afternoon .shift-head { background: #FFF7E8; }
.shift-night .shift-head { background: #F9F0FF; }

.shift-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.shift-morning .shift-dot { background: #00B42A; }
.shift-afternoon .shift-dot { background: #FF7D00; }
.shift-night .shift-dot { background: #722ED1; }

.shift-name {
  font-size: 13px;
  font-weight: 600;
  color: #1D2129;
}
.shift-time {
  font-size: 11px;
  color: #86909C;
  margin-left: auto;
}

.shift-body {
  padding: 14px;
  min-height: 120px;
}
.shift-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 0;
  color: #C9CDD4;
  font-size: 12px;
}
.duty-tag {
  margin: 0 8px 8px 0;
  padding: 0 12px;
  height: 32px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  font-size: 13px;
}
.duty-emp-id {
  color: #86909C;
  font-size: 11px;
  margin-left: 4px;
}

.form-row {
  max-width: 720px;
}
.duty-form {
  margin-top: 4px;
}

.mb-4 {
  margin-bottom: 16px;
}
.ml-2 {
  margin-left: 8px;
}
.mt-2 {
  margin-top: 8px;
}
.p-3 {
  padding: 12px;
}
.rounded {
  border-radius: 6px;
}

@media (max-width: 900px) {
  .duty-shifts { grid-template-columns: 1fr; }
}

/* ==================== 排班矩阵 ==================== */
.matrix-card .panel-header {
  flex-wrap: wrap;
  gap: 8px;
}
.matrix-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.matrix-wrap {
  overflow-x: auto;
}
.matrix-empty {
  padding: 20px;
  text-align: center;
}
.matrix-grid {
  display: grid;
  min-width: 720px;
  border: 1px solid #E5E6EB;
  border-radius: 8px;
  overflow: hidden;
  background: #F2F3F5;
  gap: 1px;
}
.matrix-th,
.matrix-row-head,
.matrix-cell {
  background: #fff;
  padding: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.matrix-th {
  flex-direction: column;
  gap: 2px;
  background: #F7F8FA;
  font-size: 12px;
  color: #4E5969;
  min-height: 48px;
}
.matrix-th.is-today {
  background: #E8F3FF;
  color: #165DFF;
}
.matrix-corner {
  font-weight: 600;
  color: #1D2129;
}
.th-date {
  font-size: 13px;
  font-weight: 600;
}
.th-weekday {
  font-size: 11px;
  color: #86909C;
}
.matrix-row-head {
  justify-content: flex-start;
  gap: 8px;
  min-width: 150px;
  padding: 8px 12px;
}
.rh-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.3;
}
.rh-name {
  font-size: 13px;
  font-weight: 600;
  color: #1D2129;
}
.rh-emp {
  font-size: 11px;
  color: #86909C;
}
.matrix-cell {
  cursor: pointer;
  min-height: 48px;
  transition: background 0.15s;
  position: relative;
  flex-wrap: wrap;
  gap: 2px;
}
.matrix-cell:hover {
  background: #F2F3F5;
}
.matrix-cell .cell-tag {
  margin: 1px;
  white-space: nowrap;
}
.matrix-cell.cell-leave-fullday {
  background: #FFF1F0;
}
.matrix-cell.cell-leave-fullday:hover {
  background: #FFE0E0;
}
.matrix-cell .cell-rest {
  color: #C9CDD4;
  font-size: 12px;
}

/* 单元格编辑浮动菜单 */
.cell-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2000;
}
.cell-menu {
  position: fixed;
  z-index: 2001;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  padding: 6px;
  min-width: 140px;
  border: 1px solid #E5E6EB;
}
.cell-menu-title {
  font-size: 11px;
  color: #86909C;
  padding: 4px 8px;
  border-bottom: 1px solid #F2F3F5;
  margin-bottom: 4px;
}
.cell-menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  color: #1D2129;
  transition: background 0.15s;
}
.cell-menu-item:hover {
  background: #F2F3F5;
}
.cell-menu-item.danger {
  color: #F53F3F;
}
.cell-menu-item.danger:hover {
  background: #FFF1F0;
}
.cell-menu-item .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-morning { background: #00B42A; }
.dot-afternoon { background: #FF7D00; }
.dot-night { background: #722ED1; }
.cell-menu-divider {
  height: 1px;
  background: #F2F3F5;
  margin: 4px 0;
}
</style>
