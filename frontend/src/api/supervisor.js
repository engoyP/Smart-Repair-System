import request from './index'

export const listDutyToday = (params) => {
  return request({
    url: '/duty-schedules/today',
    method: 'get',
    params
  })
}

export const createDutyBatch = (data) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'post',
    data
  })
}

export const listTechnicians = (params) => {
  return request({
    url: '/users',
    method: 'get',
    params: { role: 'technician', ...params }
  })
}

export const scheduleList = (params) => {
  return request({
    url: '/duty-schedules',
    method: 'get',
    params
  })
}

export const scheduleCreate = (data) => {
  return request({
    url: '/duty-schedules',
    method: 'post',
    data
  })
}

export const scheduleDelete = (id) => {
  return request({
    url: `/duty-schedules/${id}`,
    method: 'delete'
  })
}

export const scheduleBatchDelete = (ids) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'delete',
    data: { ids }
  })
}

export const leaveBatchCreate = (data) => {
  return request({
    url: '/duty-schedules/leave/batch',
    method: 'post',
    data
  })
}

export const leaveSummary = (date) => {
  return request({
    url: '/duty-schedules/leave/summary',
    method: 'get',
    params: { date }
  })
}

export const leaveSummaryByDate = leaveSummary

export const workOrderTransition = (workOrderId, data) => {
  return request({
    url: `/work-orders/${workOrderId}/transition`,
    method: 'post',
    data
  })
}

// ===========================================
// Phase 2.1: 请假申请 API
// ===========================================

/** 提交前预检：未完成工单冲突 + 在岗人数不足警告 */
export const leavePreCheck = (params) => {
  return request({
    url: '/leave-requests/check-conflicts',
    method: 'get',
    params
  })
}

/** 提交请假申请 */
export const leaveSubmit = (data) => {
  return request({
    url: '/leave-requests',
    method: 'post',
    data
  })
}

/** 请假列表（主管端分页） */
export const leaveList = (params) => {
  return request({
    url: '/leave-requests',
    method: 'get',
    params
  })
}

/** 我的请假记录 */
export const leaveMyList = (params) => {
  return request({
    url: '/leave-requests/my',
    method: 'get',
    params
  })
}

/** 请假详情（含冲突工单 + 在岗人数附加信息） */
export const leaveDetail = (id) => {
  return request({
    url: `/leave-requests/${id}`,
    method: 'get'
  })
}

/** 主管批准（携带 substitute_user_id 强制顶岗人） */
export const leaveApprove = (id, data) => {
  return request({
    url: `/leave-requests/${id}/approve`,
    method: 'post',
    data
  })
}

/** 主管拒绝 */
export const leaveReject = (id, data) => {
  return request({
    url: `/leave-requests/${id}/reject`,
    method: 'post',
    data
  })
}

/** 师傅撤销（仅 PENDING 状态） */
export const leaveCancel = (id) => {
  return request({
    url: `/leave-requests/${id}/cancel`,
    method: 'post'
  })
}

/** 复制上周排班矩阵 */
export const copyLastWeekSchedule = (data) => {
  return request({
    url: '/duty-schedules/copy-week',
    method: 'post',
    data
  })
}

/** 查询周排班矩阵 */
export const listWeekScheduleMatrix = (params) => {
  return request({
    url: '/duty-schedules/week',
    method: 'get',
    params
  })
}

export const batchCreateDutySchedules = (data) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'post',
    data
  })
}
