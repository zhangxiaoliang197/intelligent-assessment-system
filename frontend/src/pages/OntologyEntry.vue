<template><div class="ontology-entry"><p>{{ error || '正在打开装备协同推演…' }}</p><el-button v-if="error" @click="$router.push('/ontology/library')">进入本体管理</el-button></div></template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
const router = useRouter(), error = ref('')
onMounted(async () => { try { const response = await api.post('/ontology/examples/wargame'); await router.replace(`/ontology/${response.data.id}`) } catch (e: any) { error.value = e?.response?.data?.detail || e.message || '示例载入失败' } })
</script>
<style scoped>.ontology-entry{min-height:100vh;display:grid;place-content:center;text-align:center;background:var(--bg-page);color:var(--primary-600);gap:14px}</style>
