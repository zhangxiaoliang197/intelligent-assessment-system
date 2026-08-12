<template>
  <div class="situation-query-bar">
    <el-input
      v-model="inner"
      type="textarea"
      :rows="2"
      :placeholder="placeholder"
      resize="none"
      :disabled="disabled"
      @keydown="sendMessageOnEnter($event, onGenerate)"
    />
    <div class="query-actions">
      <span class="query-hint">Enter 发送，Shift + Enter 换行</span>
      <el-button
        type="primary"
        :icon="Promotion"
        :loading="loading"
        :disabled="disabled || !inner.trim()"
        @click="onGenerate"
      >
        {{ loading ? '生成中' : '生成态势图' }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import { sendMessageOnEnter } from '@/utils/messageInput'

const props = withDefaults(defineProps<{
  modelValue?: string
  placeholder?: string
  loading?: boolean
  disabled?: boolean
}>(), {
  modelValue: '',
  placeholder: '请输入您的问题，例如：某区域近期装备损耗与战备状态',
  loading: false,
  disabled: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'generate', v: string): void
}>()

const inner = ref(props.modelValue)

watch(() => props.modelValue, (v) => { inner.value = v })
watch(inner, (v) => emit('update:modelValue', v))

function onGenerate() {
  if (!inner.value.trim() || props.loading) return
  emit('generate', inner.value.trim())
}
</script>

<style scoped>
.situation-query-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.query-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.query-hint {
  font-size: 12px;
  color: #909399;
}
</style>
