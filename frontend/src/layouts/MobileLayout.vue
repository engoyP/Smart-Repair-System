<template>
  <div class="mobile-app">
    <!-- 顶部状态栏 -->
    <div class="mobile-header">
      <span class="header-back" v-if="showBack" @click="$router.back()">&lt; 返回</span>
      <span class="header-title">{{ title }}</span>
      <span class="header-user" @click="showUserMenu = !showUserMenu">{{ user.name || '用户' }}</span>
    </div>

    <!-- 主内容 -->
    <div class="mobile-body">
      <router-view />
    </div>

    <!-- 底部 Tab -->
    <div class="mobile-tabs" v-if="showTabs">
      <div class="tab-item" :class="{ active: route.path.startsWith('/m/report') }" @click="$router.push('/m/report')">
        <span class="tab-icon">+</span>
        <span class="tab-label">故障上报</span>
      </div>
      <div class="tab-item" :class="{ active: route.path.startsWith('/m/queue') }" @click="$router.push('/m/queue')">
        <span class="tab-icon">#</span>
        <span class="tab-label">我的工单</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const showBack = computed(() => !['/m/report', '/m/queue'].includes(route.path))
const showTabs = computed(() => ['/m/report', '/m/queue'].includes(route.path))
const title = computed(() => route.meta?.title || '维修助手')

const user = { name: '张工' } // 后续从钉钉免登获取
const showUserMenu = ref(false)
</script>

<style scoped>
.mobile-app {
  max-width: 430px;
  margin: 0 auto;
  min-height: 100vh;
  background: #F5F6F8;
  display: flex;
  flex-direction: column;
  position: relative;
}

.mobile-header {
  height: 44px;
  background: #1677FF;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  font-size: 16px;
  flex-shrink: 0;
}
.header-back { cursor: pointer; font-size: 14px; }
.header-title { font-weight: 500; }
.header-user { cursor: pointer; font-size: 13px; opacity: 0.9; }

.mobile-body {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 60px;
}

.mobile-tabs {
  position: fixed;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100%;
  max-width: 430px;
  height: 56px;
  background: #fff;
  border-top: 1px solid #EBEDF0;
  display: flex;
  z-index: 100;
}
.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #86909C;
  font-size: 12px;
  transition: color .2s;
}
.tab-item.active { color: #1677FF; }
.tab-icon { font-size: 22px; line-height: 1; margin-bottom: 2px; }
.tab-label { font-size: 11px; }
</style>
