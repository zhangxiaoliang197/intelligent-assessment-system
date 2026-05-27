<template>
  <Layout>
    <div class="indicator-container">
      <div class="sidebar">
        <div class="sidebar-section">
          <h3 class="sidebar-title">导航</h3>
          <div class="nav-item" @click="goTo('/knowledge')">
            <el-icon><Collection /></el-icon>
            <span>知识库</span>
          </div>
          <div class="nav-item" @click="goTo('/ontology')">
            <el-icon><Box /></el-icon>
            <span>本体模型</span>
          </div>
        </div>
        <div class="sidebar-section">
          <h3 class="sidebar-title">历史记录</h3>
          <div class="history-list custom-scroll">
            <div
              v-for="item in historyList"
              :key="item.id"
              class="history-item"
              @click="loadHistory(item)"
            >
              <el-icon><PieChart /></el-icon>
              <span>{{ item.title }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="main-content">
        <div class="tags-section">
          <div class="tag-group">
            <h4>推荐指标</h4>
            <div class="tags">
              <el-tag
                v-for="tag in recommendedIndicators"
                :key="tag"
                class="tag-item"
                @click="selectIndicator(tag)"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
          <div class="tag-group">
            <h4>热门指标</h4>
            <div class="tags">
              <el-tag
                v-for="tag in hotIndicators"
                :key="tag"
                type="warning"
                class="tag-item"
                @click="selectIndicator(tag)"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
        </div>
        <div class="indicator-tree-container">
          <div class="tree-header">
            <h3>指标树状图</h3>
            <div class="tree-legend">
              <span class="legend-item">
                <span class="legend-color" style="background: #3b82f6"></span>
                知识库指标
              </span>
              <span class="legend-item">
                <span class="legend-color" style="background: #9ca3af"></span>
                大模型生成
              </span>
            </div>
          </div>
          <div ref="treeChartRef" class="tree-chart"></div>
        </div>
        <div class="detail-section">
          <h3>指标详情</h3>
          <el-descriptions v-if="selectedIndicator" :column="2" border>
            <el-descriptions-item label="指标名称">
              {{ selectedIndicator.name }}
            </el-descriptions-item>
            <el-descriptions-item label="指标类型">
              <el-tag :type="selectedIndicator.source === 'knowledge' ? 'primary' : 'info'">
                {{ selectedIndicator.source === 'knowledge' ? '知识库' : '大模型生成' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="定义" :span="2">
              {{ selectedIndicator.definition }}
            </el-descriptions-item>
            <el-descriptions-item label="计算公式" :span="2">
              {{ selectedIndicator.formula }}
            </el-descriptions-item>
            <el-descriptions-item label="评估标准" :span="2">
              {{ selectedIndicator.criteria }}
            </el-descriptions-item>
          </el-descriptions>
          <div v-else class="empty-detail">
            <p>请选择指标查看详情</p>
          </div>
        </div>
        <div class="input-area">
          <el-input
            v-model="inputMessage"
            type="textarea"
            :rows="2"
            placeholder="输入指标需求，如：帮我分析火力打击任务完成度指标..."
            @keyup.enter.ctrl="analyzeIndicator"
          />
          <div class="input-actions">
            <el-button type="primary" @click="analyzeIndicator">
              分析指标
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Collection, Box, PieChart } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'

const router = useRouter()
const treeChartRef = ref<HTMLElement | null>(null)
const inputMessage = ref('')
const selectedIndicator = ref<any>(null)
const historyList = ref([
  { id: 1, title: '作战效能指标' },
  { id: 2, title: '打击能力指标' }
])

const recommendedIndicators = [
  '作战效能',
  '打击能力',
  '生存能力',
  '保障能力'
]

const hotIndicators = [
  '任务完成度',
  '响应时间',
  '准确率',
  '覆盖率'
]

const goTo = (path: string) => {
  router.push(path)
}

const loadHistory = (item: any) => {
  ElMessage.info('加载历史记录')
}

const selectIndicator = (indicator: string) => {
  inputMessage.value = `分析${indicator}指标`
  analyzeIndicator()
}

const analyzeIndicator = () => {
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入指标需求')
    return
  }
  ElMessage.success('开始分析指标')
  initTreeChart()
}

const initTreeChart = () => {
  if (!treeChartRef.value) return

  const chart = echarts.init(treeChartRef.value)

  const option = {
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove'
    },
    series: [
      {
        type: 'tree',
        data: [
          {
            name: '作战效能',
            children: [
              {
                name: '打击能力',
                children: [
                  { name: '命中率', source: 'knowledge' },
                  { name: '摧毁率', source: 'knowledge' },
                  { name: '突防率', source: 'llm' }
                ]
              },
              {
                name: '生存能力',
                children: [
                  { name: '存活率', source: 'knowledge' },
                  { name: '防护能力', source: 'llm' }
                ]
              },
              {
                name: '保障能力',
                children: [
                  { name: '补给效率', source: 'knowledge' },
                  { name: '维护能力', source: 'llm' }
                ]
              }
            ]
          }
        ],
        symbolSize: 10,
        label: {
          position: 'left',
          verticalAlign: 'middle',
          align: 'right'
        },
        leaves: {
          label: {
            position: 'right',
            verticalAlign: 'middle',
            align: 'left'
          }
        },
        expandAndCollapse: true,
        initialTreeDepth: -1
      }
    ]
  }

  chart.setOption(option)

  chart.on('click', (params: any) => {
    if (params.data.source) {
      selectedIndicator.value = {
        name: params.data.name,
        source: params.data.source,
        definition: '该指标的定义和详细说明在此展示...',
        formula: '计算公式：X = (A + B) / C × 100%',
        criteria: '优秀: ≥90, 良好: ≥80, 合格: ≥70'
      }
    }
  })
}

onMounted(() => {
  nextTick(() => {
    initTreeChart()
  })
})
</script>

<style scoped>
.indicator-container {
  display: flex;
  height: 100%;
  background: white;
}

.sidebar {
  width: 260px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  padding: 1.5rem;
  overflow-y: auto;
}

.sidebar-section {
  margin-bottom: 2rem;
}

.sidebar-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  margin-bottom: 1rem;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  color: #374151;
}

.nav-item:hover {
  background: #e2e8f0;
}

.history-list {
  max-height: 400px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  color: #6b7280;
  font-size: 0.9rem;
}

.history-item:hover {
  background: #e2e8f0;
  color: #374151;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  overflow-y: auto;
}

.tags-section {
  display: flex;
  gap: 2rem;
  margin-bottom: 1.5rem;
}

.tag-group {
  flex: 1;
}

.tag-group h4 {
  font-size: 0.9rem;
  color: #64748b;
  margin-bottom: 0.75rem;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tag-item {
  cursor: pointer;
  transition: all 0.2s;
}

.tag-item:hover {
  transform: scale(1.05);
}

.indicator-tree-container {
  margin-bottom: 1.5rem;
  padding: 1.5rem;
  background: #f9fafb;
  border-radius: 0.75rem;
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.tree-header h3 {
  margin: 0;
  color: #374151;
}

.tree-legend {
  display: flex;
  gap: 1.5rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  color: #6b7280;
}

.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.tree-chart {
  height: 300px;
}

.detail-section {
  margin-bottom: 1.5rem;
}

.detail-section h3 {
  margin: 0 0 1rem 0;
  color: #374151;
}

.empty-detail {
  padding: 3rem;
  text-align: center;
  color: #9ca3af;
  background: #f9fafb;
  border-radius: 0.5rem;
}

.input-area {
  background: white;
  padding: 1rem;
  border-radius: 0.75rem;
  box-shadow: 0 -4px 6px rgba(0, 0, 0, 0.05);
}

.input-actions {
  margin-top: 1rem;
  display: flex;
  justify-content: flex-end;
}
</style>
