<template>
  <!-- AI 统一头像：蓝底圆形 + 当前模块符号，禁止再出现 “AI” 文字 -->
  <el-avatar :size="size" class="assistant-avatar">
    <el-icon :size="iconSize"><component :is="icon" /></el-icon>
  </el-avatar>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ChatDotRound, PieChart, Document, MagicStick } from '@element-plus/icons-vue'

// AI 头像统一由当前路由决定模块符号，四个模块共用一份映射
const props = withDefaults(defineProps<{ size?: number }>(), { size: 40 })

const route = useRoute()

// 路由 → 模块符号（与门户首页、四模块切换栏保持一致）
const MODULE_ICONS: Record<string, any> = {
  '/qa': ChatDotRound,
  '/indicator': PieChart,
  '/evaluation': Document,
  '/situation-page': MagicStick,
  '/interactive': MagicStick
}

const icon = computed(() => MODULE_ICONS[route.path] || ChatDotRound)
const iconSize = computed(() => Math.round(props.size * 0.55))
</script>

<style scoped>
.assistant-avatar {
  flex-shrink: 0;
  background: var(--primary-500);
  color: #fff;
}
</style>
