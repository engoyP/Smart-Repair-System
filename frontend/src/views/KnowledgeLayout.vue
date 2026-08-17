<template>
  <div class="knowledge-hub">
    <div class="hub-header">
      <div>
        <h2 class="hub-title">知识库</h2>
        <p class="hub-desc">维修案例、设备手册统一检索与管理</p>
      </div>
      <el-button
        v-if="activeTab === 'list'"
        type="primary"
        @click="$router.push('/knowledge/new')"
      >
        新增知识
      </el-button>
    </div>

    <el-tabs
      v-if="activeTab"
      :model-value="activeTab"
      class="hub-tabs"
      @tab-change="handleTabChange"
    >
      <el-tab-pane label="知识列表" name="list" />
      <el-tab-pane label="设备手册" name="manuals" />
    </el-tabs>

    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const activeTab = computed(() => route.meta.knowledgeTab || '')

const handleTabChange = (name) => {
  router.push(`/knowledge/${name}`)
}
</script>

<style scoped>
.knowledge-hub {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hub-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.hub-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.3;
}

.hub-desc {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.hub-tabs {
  flex-shrink: 0;
}

.hub-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
</style>
