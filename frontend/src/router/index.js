import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '数据驾驶舱' } },
        { path: 'work-orders', name: 'WorkOrders', component: () => import('../views/WorkOrders.vue'), meta: { title: '维修报表' } },
        { path: 'work-orders/new', name: 'WorkOrderCreate', component: () => import('../views/WorkOrderForm.vue'), meta: { title: '新建工单' } },
        { path: 'work-orders/:id', name: 'WorkOrderForm', component: () => import('../views/WorkOrderForm.vue'), meta: { title: '工单详情' } },
        { path: 'devices', name: 'Devices', component: () => import('../views/Devices.vue'), meta: { title: '设备监控' } },
        { path: 'devices/new', name: 'DeviceCreate', component: () => import('../views/DeviceForm.vue'), meta: { title: '新增设备' } },
        { path: 'devices/:id', name: 'DeviceForm', component: () => import('../views/DeviceForm.vue'), meta: { title: '设备详情' } },
        {
          path: 'knowledge',
          name: 'Knowledge',
          component: () => import('../views/KnowledgeLayout.vue'),
          redirect: '/knowledge/list',
          children: [
            { path: 'list', name: 'KnowledgeList', component: () => import('../views/Knowledge.vue'), meta: { title: '知识列表', knowledgeTab: 'list' } },
            { path: 'manuals', name: 'KnowledgeManuals', component: () => import('../views/ManualCodes.vue'), meta: { title: '设备手册', knowledgeTab: 'manuals' } },
            { path: 'new', name: 'KnowledgeCreate', component: () => import('../views/KnowledgeForm.vue'), meta: { title: '新增知识' } },
            { path: ':id', name: 'KnowledgeForm', component: () => import('../views/KnowledgeForm.vue'), meta: { title: '知识详情' } },
          ],
        },
        { path: 'spare-parts', name: 'SpareParts', component: () => import('../views/SpareParts.vue'), meta: { title: '库存管理' } },
        { path: 'spare-parts/new', name: 'SparePartCreate', component: () => import('../views/SparePartForm.vue'), meta: { title: '新增备件' } },
        { path: 'spare-parts/:id', name: 'SparePartForm', component: () => import('../views/SparePartForm.vue'), meta: { title: '备件详情' } },
        { path: 'warehouse', name: 'Warehouse', component: () => import('../views/Warehouse.vue'), meta: { title: '仓库库存' } },
        { path: 'users', name: 'Users', component: () => import('../views/Users.vue'), meta: { title: '用户管理' } },
        { path: 'categories', name: 'Categories', component: () => import('../views/Categories.vue'), meta: { title: '分类管理' } },
        { path: 'search', name: 'Search', component: () => import('../views/Search.vue'), meta: { title: '知识搜索' } },
        { path: 'ai-assistant', name: 'AiAssistant', component: () => import('../views/AiAssistant.vue'), meta: { title: 'AI 问答看板' } },
        { path: 'fault-codes', name: 'FaultCodes', component: () => import('../views/FaultCodes.vue'), meta: { title: '故障码管理' } },
        { path: 'work-order-imports', name: 'WorkOrderImports', component: () => import('../views/ImportWorkOrders.vue'), meta: { title: '历史工单导入', roles: ['ADMIN', 'TECHNICIAN'] } },
        { path: 'profile', name: 'Profile', component: () => import('../views/Profile.vue'), meta: { title: '个人设置' } },
        { path: 'security', name: 'Security', component: () => import('../views/Security.vue'), meta: { title: '账号安全' } },
        { path: 'help', name: 'Help', component: () => import('../views/Help.vue'), meta: { title: '帮助中心' } },
        { path: 'supervisor/dispatch', name: 'SupervisorDispatch', component: () => import('../views/SupervisorDispatch.vue'), meta: { title: '派工中心', roles: ['SUPERVISOR', 'ADMIN'] } },
        { path: 'supervisor/progress', name: 'SupervisorProgress', component: () => import('../views/SupervisorProgress.vue'), meta: { title: '实时进度看板', roles: ['SUPERVISOR', 'ADMIN'] } },
        { path: 'supervisor/schedule', name: 'SupervisorSchedule', component: () => import('../views/SupervisorSchedule.vue'), meta: { title: '排班管理', roles: ['SUPERVISOR', 'ADMIN'] } },
      ]
    },
    // 登录页（独立于 MainLayout）
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { title: '登录', noAuth: true },
    },
    // 移动端 H5 路由
    {
      path: '/m',
      component: () => import('../layouts/MobileLayout.vue'),
      redirect: '/m/report',
      children: [
        { path: 'report', name: 'MobileReport', component: () => import('../views/mobile/WorkerSubmit.vue'), meta: { title: '故障上报' } },
        { path: 'queue', name: 'TechQueue', component: () => import('../views/mobile/TechQueue.vue'), meta: { title: '我的工单' } },
        { path: 'detail/:id', name: 'TechDetail', component: () => import('../views/mobile/TechDetail.vue'), meta: { title: '工单详情' } },
      ]
    }
  ]
})

// 全局导航守卫：未登录跳转登录页
router.beforeEach((to, from, next) => {
  if (!to.meta.noAuth) {
    const token = localStorage.getItem('auth_token')
    const user = localStorage.getItem('current_user')
    if (!token && !user) {
      next('/login')
      return
    }
  }
  next()
})

export default router
