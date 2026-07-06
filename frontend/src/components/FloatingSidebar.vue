<template>
  <aside class="floating-sidebar">
    <div class="sidebar-items">
      <div
        v-for="system in systems"
        :key="system.id"
        class="sidebar-item"
        :style="{ '--item-color': system.color }"
        @click="navigateToSystem(system.path)"
      >
        <div class="item-icon">
          <el-icon :size="18">
            <component :is="system.icon" />
          </el-icon>
        </div>
        <span class="item-label">{{ system.name }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Collection, Box, Cpu } from '@element-plus/icons-vue'

const router = useRouter()

const systems = [
  {
    id: 1,
    name: '知识库',
    icon: Collection,
    color: '#3b82f6',
    path: '/knowledge'
  },
  {
    id: 2,
    name: '本体模型',
    icon: Box,
    color: '#10b981',
    path: '/ontology'
  },
  {
    id: 3,
    name: '基础管理',
    icon: Cpu,
    color: '#f59e0b',
    path: '/admin'
  }
]

const navigateToSystem = (path: string) => {
  router.push(path)
}
</script>

<style scoped>
.floating-sidebar {
  position: fixed;
  right: 28px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 50;
}

.sidebar-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 20px;
  box-shadow: var(--shadow-lg);
}

.sidebar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.sidebar-item:hover {
  background: color-mix(in srgb, var(--item-color) 8%, white);
}

.item-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--item-color) 12%, white);
  color: var(--item-color);
  transition: all var(--transition-fast);
}

.sidebar-item:hover .item-icon {
  background: var(--item-color);
  color: white;
  transform: scale(1.05);
}

.item-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  transition: color var(--transition-fast);
}

.sidebar-item:hover .item-label {
  color: var(--item-color);
}

@media (max-width: 640px) {
  .floating-sidebar {
    display: none;
  }
}
</style>