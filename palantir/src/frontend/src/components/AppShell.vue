<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, RouterLink, RouterView } from 'vue-router';
import { Boxes, Database, Network, Settings, Bell } from 'lucide-vue-next';
import tianzhiLogo from '@/assets/tianzhi-logo.png';

const route = useRoute();
const nav = [
  { label: '本体管理', path: '/ontology', icon: Boxes },
  { label: '动态本体', path: '/ontology/aegis-maneuver-causal', icon: Network },
];
const title = computed(() => route.name === 'ontology-detail' ? '本体详情' : '本体管理');
</script>

<template>
  <div class="min-h-screen bg-transparent text-slate-900">
    <aside class="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white/95 backdrop-blur lg:block">
      <div class="flex h-16 items-center gap-2.5 border-b border-slate-100 px-5">
        <img :src="tianzhiLogo" alt="天智" class="h-6 w-auto object-contain" />
        <div class="min-w-0">
          <div class="truncate text-sm font-bold tracking-wide text-slate-950">天智智能评估系统</div>
        </div>
      </div>

      <nav class="space-y-1 p-3">
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition"
          :class="route.path === item.path || (item.path !== '/ontology' && route.path.startsWith(item.path))
            ? 'bg-blue-50 text-blue-700'
            : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
        >
          <component :is="item.icon" class="h-4 w-4" />
          {{ item.label }}
        </RouterLink>
      </nav>


      <div class="absolute bottom-4 left-3 right-3 flex items-center justify-between rounded-xl border border-slate-100 bg-white p-3 text-slate-500">
        <span class="inline-flex items-center gap-2 text-xs"><Database class="h-4 w-4" /> dynamic-ontology-v6</span>
        <Settings class="h-4 w-4" />
      </div>
    </aside>

    <div class="lg:pl-64">
      <header class="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur md:px-6">
        <div class="flex items-center gap-3">
          <div class="flex items-center gap-2 lg:hidden">
            <img :src="tianzhiLogo" alt="天智" class="h-5 w-auto object-contain" />
            <span class="text-xs font-bold text-slate-900">天智智能评估系统</span>
          </div>
          <div class="hidden h-5 w-px bg-slate-200 lg:block" />
          <h1 class="text-sm font-semibold text-slate-900">{{ title }}</h1>
        </div>
        <div class="flex items-center gap-2">
          <button class="graph-tool" title="通知"><Bell class="h-4 w-4" /></button>
          <div class="rounded-full bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700">管理员</div>
        </div>
      </header>
      <main class="p-4 md:p-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>
