<template>
  <!-- 四模块切换卡片：数据与跳转来自 useToolNav，各模块页面共用同一份样式 -->
  <div class="tools-bar">
    <div
      v-for="tool in tools"
      :key="tool.id"
      :class="['tool-item', { current: tool.current }]"
      @click="navigateToTool(tool.path)"
    >
      <div class="tool-icon">
        <el-icon :size="16" :color="tool.current ? 'white' : tool.color">
          <component :is="tool.icon" />
        </el-icon>
      </div>
      <span class="tool-name">{{ tool.name }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useToolNav } from '@/composables/useToolNav'

const { tools, navigateToTool } = useToolNav()
</script>

<style scoped>
.tools-bar {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.tools-bar .tool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--gray-50);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid var(--border-light);
}

.tools-bar .tool-item:hover {
  background: white;
  border-color: var(--primary-300);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

.tools-bar .tool-item.current {
  background: var(--primary-500);
  border-color: var(--primary-500);
  cursor: default;
}

.tools-bar .tool-icon {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
}

.tools-bar .tool-item.current .tool-icon {
  background: transparent;
}

.tools-bar .tool-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.tools-bar .tool-item.current .tool-name {
  color: white;
}

.tools-bar .tool-item:hover .tool-name {
  color: var(--primary-600);
}

.tools-bar .tool-item.current:hover .tool-name {
  color: white;
}
</style>
