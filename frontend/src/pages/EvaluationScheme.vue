<template>
  <Layout>
    <div class="evaluation-container">
      <div class="page-header">
        <h2>方案评估</h2>
        <el-button type="primary" @click="createNewScheme">新建评估方案</el-button>
      </div>
      <div class="content">
        <el-empty description="评估方案管理功能开发中">
          <el-button type="primary">了解详情</el-button>
        </el-empty>
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'

const createNewScheme = () => {
  ElMessage.info('新建评估方案功能开发中')
}
</script>

<style scoped>
.evaluation-container {
  height: 100%;
  padding: 2rem;
  background: white;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.page-header h2 {
  margin: 0;
  color: #374151;
}

.content {
  display: flex;
  align-items: center;
  justify-content: center;
  height: calc(100% - 80px);
}
</style>
