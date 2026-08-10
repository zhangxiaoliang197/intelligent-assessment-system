# 智能评估系统 - 产品需求文档（PRD）

**版本**：V2.0  
**日期**：2026-08-07  
**状态**：已实现

---

## 一、项目概述

### 1.1 项目背景

本系统是面向**作战指挥场景**的智能评估平台，为军事指挥、作战决策、效能评估等关键环节提供智能化支持。系统以"AI 分析师"为定位，将非结构化的分析需求自动转化为结构化的数据库查询、指标计算与综合结论。

### 1.2 核心价值

| 断层 | 传统方式 | 本系统解决 |
|------|----------|-----------|
| **需求→数据** | 人工理解需求 → 找表 → 手写 SQL | AI 自动选表 + Text-to-SQL，零 SQL 门槛 |
| **数据→洞察** | 导出 Excel → 人工制图制表 → 数小时 | 自动执行 + LLM 分析，秒级出结论 |
| **知识→决策** | 专业知识散落在文档中，无法系统化调用 | RAG（Qdrant+BGE+BM25 混合检索）统一管理 |

### 1.3 目标用户

| 角色 | 使用场景 | 核心诉求 |
|------|----------|----------|
| **指挥决策人员** | 快速了解战损/战果/消耗态势 | 自然语言提问，即刻获得数据+图表+结论 |
| **参谋/分析人员** | 构建指标体系、评估作战方案 | 知识库辅助 + LLM 推理 + Skill 编排 |
| **系统管理员** | 配置数据源、管理知识库、维护本体模型 | Web 界面操作，无需命令行 |

---

## 二、系统架构设计

### 2.1 整体架构

系统采用**前后端分离**微服务架构，共 8 个 Docker 容器（7 应用 + Qdrant 向量数据库）：

```
                    ┌──────────────────────┐
                    │   Nginx (端口 10086)   │
                    │   Vue 3 前端 SPA       │
                    └──────┬───────────────┘
                           │
     ┌──────────┬──────────┼──────────┬──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼          ▼
   QA        Know-      Indi-      Onto-      Eval-      Admin
  10253      ledge      cator      logy      uation      (Java)
  FastAPI    10252      10254      10256      10255      10258
  + 多Agent  +Qdrant    +状态机    +分步构建    +CRUD     + JDBC
                 │                                            │
                 ▼                                       JDBC ▼
            Qdrant:6333                              MySQL / Oracle
            向量检索                                   / 达梦 / PG /
                                                      SQL Server
```

### 2.2 服务职责速览

| 服务 | 端口 | 技术栈 | 核心职责 |
|------|------|--------|----------|
| **Frontend** | 10086 | Vue 3 + TS + Vite + Element Plus + ECharts + Leaflet | 门户、问答、指标树、评估、地图、知识库、本体图、后台管理 |
| **QA Service** | 10253 | Python FastAPI | 系统大脑：智能问答 RAG + 多智能体评估分析 + Skill 全生命周期管理 + 定时调度 + 批量执行 |
| **Knowledge Service** | 10252 | Python FastAPI + Qdrant + BGE | 文档解析+分片→BGE 向量化 → Qdrant 语义检索 + BM25 关键词 → RRF 融合 |
| **Indicator Service** | 10254 | Python FastAPI | 会话状态机驱动：概念问答 / LLM 生成指标体系 / 追问确认 / 数据库查询管线 |
| **Ontology Service** | 10256 | Python FastAPI | 本体 CRUD + 3 步构建流水线（概念提取→层次结构→生成） + 图谱可视化 + 数据绑定 |
| **Evaluation Service** | 10255 | Python FastAPI | 评估方案 CRUD（轻量服务，实际执行由 QA Service 的 Skill 引擎完成） |
| **Admin Service** | 10258 | Java Spring Boot 3 | 配置中枢：数据源/驱动/数据集/字段标注/指标库/LLM 配置/地图配置/SQL 安全执行 |
| **Qdrant** | 6333 | Qdrant | 向量数据库，知识库语义检索存储 |

### 2.3 技术选型

#### 前端
- **框架**：Vue 3 + Composition API + TypeScript
- **UI 组件库**：Element Plus（自动导入）+ Tailwind CSS
- **状态管理**：Pinia
- **路由管理**：Vue Router 4（History 模式）
- **构建工具**：Vite 5
- **图表库**：ECharts（指标树状图、知识图谱）
- **地图库**：Leaflet + leaflet-draw + gcoord（WGS84→GCJ02 坐标转换）
- **语音交互**：Web Speech API
- **Markdown**：marked + DOMPurify（安全渲染）

#### AI 服务层（Python）
- **Web 框架**：FastAPI + Uvicorn
- **向量检索**：Qdrant + BGE-small-zh-v1.5 嵌入 + BM25 本地倒排 + RRF 融合
- **LLM 集成**：OpenAI 兼容 API（支持 deepseek/vllm/openai 等），urllib 直连
- **流式响应**：SSE (Server-Sent Events) / NDJSON
- **文档解析**：PyPDF2 + python-docx（含表格）
- **会话持久化**：JSON 文件（原子写入 + .bak 备份）
- **Skill 执行存储**：SQLite

#### 业务服务层（Java）
- **核心框架**：Spring Boot 3.x + Spring Data JPA
- **数据库**：JPA 自动建表（ddl-auto: update）
- **多数据库连接**：JDBC + URLClassLoader 动态加载驱动
- **支持数据库类型**：MySQL、PostgreSQL、Oracle、达梦 V8、SQL Server

---

## 三、功能模块设计

### 3.1 门户页面（Portal）

系统的统一入口，集成所有功能模块导航和统一输入框。

- **统一输入框**：文本输入 + 文件上传（文档/图片） + 语音输入
- **工具入口**：智能问答、指标分析、评估分析
- **辅助系统**：知识库、本体模型、基础管理

### 3.2 智能问答（QA Service）

**核心能力**：

- **RAG 检索增强**：知识库混合检索（Qdrant 语义 + BM25 关键词） → LLM 生成答案，流式返回
- **多轮对话**：滑动窗口上下文（默认 5 轮），会话持久化
- **多模态输入**：支持图片上传（需多模态模型如 gpt-4o/qwen-vl）
- **地图标注**：LLM 输出区域/路线标注格式 → 前端 Leaflet 渲染
- **引用来源**：区分知识库引用 [N] 与 LLM 生成内容
- **查询分类**：关键词+LLM 三分类（concept_qa / indicator_analysis / general_chat）

**API 端点**：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/qa/chat` | 非流式问答 |
| POST | `/qa/chat/stream` | 流式问答（NDJSON） |
| POST | `/qa/classify-query` | 查询三分类 |
| POST | `/attachment/upload` | 文档上传解析 |
| GET | `/attachment/{id}/download` | 文档下载 |
| POST | `/image/upload` | 图片上传（≤10MB） |
| GET | `/model/supports-image` | 多模态模型检测 |
| GET/POST/PUT/DELETE | `/qa/session/*` | 会话管理 |
| GET | `/qa/history` | 历史记录 |
| GET/POST/PUT/DELETE | `/config/llm/*` | LLM 配置代理 |

### 3.3 评估分析（Evaluation）— 多智能体协同 + Skill 引擎

QA Service 的评估子系统是系统最复杂的部分，包含了两种执行路径：

#### A. Skill 引擎（声明式编排）

用户可以创建声明式的评估 Skill，定义步骤序列、数据源映射、依赖关系、失败策略等。系统根据 Skill 定义自动执行完整的评估流程。

**Skill 生命周期管理**：
- 创建/更新/删除 Skill（乐观锁修订检查）
- 发布/归档/版本回滚
- 克隆/模板实例化
- 分享/导入/导出
- AI 草案生成（LLM 辅助创建 Skill）
- 收藏管理

**Skill 执行能力**：
- 飞行前检查（preflight）：验证 Skill 对指定数据源的可用性
- 单步试运行（trial）：调试单个步骤
- 全量执行（workflow）：按 Skill 定义依次执行所有步骤
- 批量执行（batch）：多个问题并发执行（最大 8 并发）
- 定时调度（schedule）：Cron 表达式定时触发，后台轮询执行
- 执行对比（compare）：多个执行结果横向对比

**Skill 步骤操作类型**：
- `dataset_query`：基于数据集关键词自动匹配 SQL 查询
- `database_overview`：获取数据库全量表结构概览
- `table_catalog`：列出数据库中所有表名
- `table_structure`：读取指定表结构

**Skill 编排模式**：
- `sequential`：顺序执行
- `dependency`：按依赖关系（dependsOn）DAG 执行

#### B. ReAct 多智能体工作流（智能路由）

当用户未选择 Skill 时，系统自动使用 ReAct 工作流进行意图识别和智能路由：

```
用户提问
  │
  ▼
Orchestrator 意图识别 (LLM)
  │
  ├── 数据查询类 → data_query 7 步标准流程
  │    ① 意图识别 → ② 数据源探查 → ③ 检查数据集&指标
  │    → ④ 智能选表（打分机制） → ⑤ Text-to-SQL →
  │    ⑥ SQL 安全执行 → ⑦ Analyst 分析建议
  │
  ├── 作战效能 → combat_effectiveness → 预配置 SQL 模板
  │
  ├── 制空权分析 → air_superiority → 区域参数提取 + SQL 注入
  │
  └── 纯理论问答 → general_analysis → 直接 LLM
```

**SQL 安全校验**（5 层防护）：
1. 从 markdown 代码块或纯文本提取 SQL
2. 禁止 60+ 高风险函数（PG_SLEEP、UTL_HTTP 等）
3. 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE
4. 禁止多语句和注释
5. 仅允许 SELECT 和 WITH 开头

**指标查询管线**（由 Indicator Service 确认后调用）：
- 复用数据探索 → 选表 → SQL 生成 → 执行 → 分析管线

### 3.4 指标分析（Indicator Service）

**会话状态机驱动**的分析服务：

```
用户输入 "帮我分析空战效能"
  │
  ▼
查询分类 (LLM / 关键词)
  │ concept_qa → 知识库检索 + 概念问答
  │ indicator_analysis → LLM 生成指标体系 JSON
  │ general_chat → 友好对话
  ▼
LLM 生成指标体系树
  │  ├── 一级: 打击能力 → 二级: 命中率 [来源: admin-db]
  │  ├── 一级: 生存能力 → 二级: xxx [来源: llm]
  │  └── 一级: 保障能力
  ▼
前端 ECharts 树状图展示 + 追问"是否需要查询数据？"
  │
  ├── 用户确认 → 匹配数据源 → 调用 indicator-query 管线 → 执行 SQL → 展示结果
  └── 用户拒绝 → 结束
```

**指标来源标注**（代码层根据实际证据标注）：
- **admin-db**：名称匹配已配置指标（归一化完全相等 > 包含关系 > 2-gram Jaccard ≥ 0.6）
- **knowledge**：对应知识库检索结果
- **llm**：兜底，LLM 自身知识

**数据联动增强**（B 阶段）：
- 引入本体模型上下文（`ontology/context`）辅助指标生成
- 指标生成时自动注入本体概念和关系

### 3.5 知识库（Knowledge Service）

**双路混合检索 RAG 服务**：

- **文档上传**：支持 PDF/DOCX/TXT/MD/CSV，最大 100MB
- **文件解析**：
  - PDF：PyPDF2 逐页提取
  - DOCX：python-docx（含表格内容，| 分隔）
  - TXT/MD/CSV：多编码自动检测（utf-8 > gbk > gb2312 > latin-1）
- **文本分片**：chunk_size=400，overlap=100，适配 BGE-small-zh-v1.5（512 token 上限）
- **双路索引**：
  - 语义向量：BGE 嵌入 → Qdrant COSINE 相似度检索
  - 关键词：jieba 分词 → BM25Okapi 本地倒排索引
- **融合排序**：RRF（Reciprocal Rank Fusion），k=60
- **分类/标签管理**：文档分类、标签过滤
- **全文重建索引**：支持 reindex

**API 端点**：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/knowledge/upload` | 上传文档 |
| POST | `/knowledge/batch-upload` | 批量上传 |
| POST | `/knowledge/search` | 混合检索 |
| GET | `/knowledge/list` | 文档列表 |
| GET | `/knowledge/stats` | 统计信息 |
| GET/POST/DELETE | `/knowledge/categor*` | 分类管理 |
| GET | `/knowledge/tags` | 标签列表 |
| GET/PUT/DELETE | `/knowledge/{id}` | 文档详情/更新/删除 |
| POST | `/knowledge/parse/{id}` | 重新解析 |
| POST | `/knowledge/reindex` | 重建索引 |

### 3.6 本体模型（Ontology Service）

**核心能力**：

- **本体 CRUD**：创建/更新/删除本体模型，设置默认本体，导入/导出 JSON
- **实体管理**：添加/更新/删除概念节点，支持属性字段和类型标注
- **关系管理**：创建/删除有向边，支持权重和类型
- **图谱数据**：聚合 nodes/links 供前端 ECharts 可视化
- **路径查询**：BFS 最短路径
- **数据绑定（B 阶段）**：实体绑定数据字段、关系绑定指标
- **上下文接口**：`/ontology/{id}/context` 供 indicator-service 注入 prompt

**3 步分步构建流程**：

```
上传文档 → LLM 推荐元模型 → 用户确认元模型
  → Step 1: LLM 提取概念清单
    （长文档分批 9000 字/批，500 字重叠，断点续作，概念去重合并）
  → 用户确认概念清单
  → Step 2: LLM 构建层次结构
    （同类型同组 20 个/组，跨组关系补充）
  → 用户确认层次结构
  → Step 3: LLM 最终序列化 → 生成正式本体
```

**分批/分组合并策略**：
- 概念合并：按 name 归一化去重，type 不覆盖
- 实体合并：按 name 去重，properties 浅合并
- 关系去重：按 (source, target, relation_type) 三元组去重

### 3.7 基础管理（Admin Service）

系统的配置中枢，所有 Python 服务的配置均从此获取：

**数据库配置**：
- 连接管理 / 多数据源 / 连接测试（含延迟和版本检测）
- JDBC 驱动动态加载（URLClassLoader），上传 JAR 包管理
- 支持 MySQL、PostgreSQL、Oracle、达梦 V8、SQL Server

**数据集管理**：
- 创建/更新/删除数据集，关联数据库配置
- 表结构读取（多数据库方言适配）
- 字段标注：列名、类型、主键、业务含义、数据分类
- SQL 只读执行：严格安全校验（禁止 60+ 高风险函数）

**指标管理**：
- 指标 CRUD + 分类管理
- 指标关联数据集 + 字段映射（JSON）
- 计算方法定义

**LLM 配置**：
- 多配置管理（支持 deepseek/openai/vllm）
- 活跃配置切换（互斥）
- API 连接测试

**地图服务配置**：
- 多地图服务配置管理
- 活跃配置切换

**LLM 学习数据导出**：`/api/admin/export/for-llm` 导出所有标注后的 schema + 指标

---

## 四、数据架构

### 4.1 数据存储方案

| 数据类型 | 存储方案 | 说明 |
|---------|---------|------|
| 元数据（数据库配置/数据集/指标/LLM配置） | MySQL（JPA 持久化） | 事务支持，由 admin-service 管理 |
| 向量数据 | Qdrant 向量数据库 | 语义级检索，BGE 嵌入模型 |
| BM25 关键词索引 | Python 内存 + JSON 序列化 | 关键词级检索，零额外依赖 |
| 知识库/本体/会话记录/Skill | JSON 文件（原子写入 + .bak 备份） | 读多写少，零依赖 |
| Skill 执行记录 | SQLite | 持久化执行历史、批量任务、定时调度 |
| 文档/图片 | 文件系统 | PDF、Word、图片等原始文件 |

### 4.2 服务间通信

所有跨服务调用通过 HTTP REST，内网延迟可忽略：

| 调用方 | 被调用方 | 用途 |
|--------|----------|------|
| QA Service | Admin Service | LLM 配置 / 数据库探查 / SQL 执行 / 数据集+指标查询 |
| QA Service | Knowledge Service | 知识库混合检索 |
| Indicator Service | QA Service | LLM 分类/流式生成/指标查询管线 |
| Indicator Service | Admin Service | 指标列表 / 数据源列表 |
| Indicator Service | Knowledge Service | 知识库检索 |
| Indicator Service | Ontology Service | 本体上下文（B 阶段） |
| Ontology Service | Admin Service | LLM 配置 |

---

## 五、部署方案

### 5.1 Docker Compose 编排（8 个容器）

| 容器 | 端口 | 镜像 |
|------|------|------|
| assessment-frontend | 10086:80 | assessment-frontend:latest |
| assessment-knowledge | 10252 | assessment-knowledge:latest |
| assessment-qa | 10253 | assessment-qa:latest |
| assessment-indicator | 10254 | assessment-indicator:latest |
| assessment-evaluation | 10255 | assessment-evaluation:latest |
| assessment-ontology | 10256 | assessment-ontology:latest |
| assessment-admin | 10258 | assessment-admin:latest |
| assessment-qdrant | 6333 | qdrant/qdrant:latest |

网络：`assessment-net`（bridge 驱动）

### 5.2 Nginx 反向代理

| 路径 | 目标容器 |
|------|----------|
| `/api/qa/*`, `/api/config/*`, `/api/evaluation/*`, `/api/attachment/*`, `/api/image/*`, `/api/model/*` | assessment-qa:10253 |
| `/api/knowledge/*` | assessment-knowledge:10252 |
| `/api/indicator/*` | assessment-indicator:10254 |
| `/api/ontology/*` | assessment-ontology:10256 |
| `/api/admin/*` | assessment-admin:10258（不重写路径） |
| `/tiles`, `/geowebcache` | 外部地图服务:9090 |

### 5.3 跨服务环境变量

| 容器 | 环境变量 | 值 |
|------|----------|-----|
| assessment-qa | `ADMIN_SERVICE_URL` | assessment-admin:10258 |
| assessment-qa | `KNOWLEDGE_SERVICE_URL` | assessment-knowledge:10252 |
| assessment-qa | `ONTOLOGY_SERVICE_URL` | assessment-ontology:10256 |
| assessment-knowledge | `QDRANT_URL` | assessment-qdrant:6333 |
| assessment-indicator | `QA_SERVICE_URL` | assessment-qa:10253 |
| assessment-indicator | `ADMIN_SERVICE_URL` | assessment-admin:10258 |
| assessment-indicator | `KNOWLEDGE_SERVICE_URL` | assessment-knowledge:10252 |
| assessment-indicator | `EVALUATION_API_URL` | assessment-qa:10253 |
| assessment-indicator | `ONTOLOGY_SERVICE_URL` | assessment-ontology:10256 |

### 5.4 离线部署

- 全量 Docker 镜像构建为 `.tar` 文件
- 内网环境 `docker load` + `docker run` 一键启动

---

## 六、前端架构

### 6.1 路由表

| 路径 | 路由名称 | 页面 | 说明 |
|------|----------|------|------|
| `/` | Portal | Portal.vue | 门户首页 |
| `/qa` | QAService | QAService.vue | 智能问答 |
| `/indicator` | IndicatorAnalysis | IndicatorAnalysis.vue | 指标分析 |
| `/evaluation` | SolutionEvaluation | SolutionEvaluation.vue | 方案评估 |
| `/evaluation/skills` | SkillsLibrary | SkillsLibrary.vue | Skill 库管理 |
| `/knowledge` | KnowledgeBase | KnowledgeBase.vue | 知识库管理 |
| `/ontology` | OntologyModel | OntologyModel.vue | 本体模型管理 |
| `/ontology/:id` | OntologyDetail | OntologyDetail.vue | 本体详情 |
| `/ontology-build/:jobId` | OntologyBuild | OntologyBuild.vue | 文档构建任务 |
| `/admin` | AdminSystem | AdminSystem.vue | 基础管理 |

### 6.2 Vite 开发代理

| 前端路径 | 代理目标 |
|----------|----------|
| `/api/qa`, `/api/config`, `/api/evaluation`, `/api/attachment`, `/api/image`, `/api/model` | localhost:10253 |
| `/api/knowledge` | localhost:10252 |
| `/api/indicator` | localhost:10254 |
| `/api/ontology` | localhost:10256 |
| `/api/admin` | localhost:10258（不重写） |
| `/tiles`, `/geowebcache` | localhost:9090 |

### 6.3 核心组件

| 组件 | 功能 |
|------|------|
| **GeoMap.vue** | Leaflet 地图可视化，支持 AI 标注/区域/路线渲染，leaflet-draw 用户手绘，WGS84→GCJ02 坐标转换 |
| **Layout.vue** | 全局布局框架，侧边栏导航 + 用户信息 |
| **FloatingSidebar.vue** | 浮动工具侧边栏 |
| **SkillEditorDialog.vue** | Skill 步骤编辑器 |
| **SkillOperationsDrawer.vue** | Skill 操作面板 |

### 6.4 Composable 组合函数

| Composable | 功能 |
|------------|------|
| **useAttachmentUpload** | 文档上传（PDF/Word/TXT，≤20MB） |
| **useImageUpload** | 图片上传（PNG/JPG/WebP 等，≤10MB） |
| **useSpeechRecognition** | 浏览器语音识别（中文普通话，连续识别） |
| **useMapPrompt** | 地图意图检测 + 经纬度列自动配对 |

---

## 七、关键技术特性

| 特性 | 技术实现 |
|------|----------|
| 混合检索 RAG | Qdrant 语义（BGE embedding + COSINE） + BM25 关键词 → RRF 融合 |
| 多智能体协同 | Orchestrator 意图路由 + 专项 Agent（作战效能/制空权） + 7 步 ReAct 工作流 |
| Skill 引擎 | 声明式步骤编排 + 预检查 + 批量执行 + Cron 定时调度 + 执行对比 |
| Text-to-SQL | 智能选表打分 → LLM 生成 → 5 层安全校验 → JDBC 只读执行 |
| 指标来源透明 | 代码层标注（admin-db / knowledge / llm），不让 LLM 自标 |
| 本体分步构建 | 3 步流水线（概念提取→层次结构→生成），长文档分批，断点续作 |
| 地图可视化 | LLM 输出区域/路线标注格式 → geoParser 解析 → Leaflet 渲染 |
| 数据安全 | SQL 执行禁止 60+ 高风险函数，仅允许 SELECT/WITH，查询超时 60s，最多 1000 行 |
| 多模态支持 | 图片上传 + 多模态模型检测 + base64 编码注入 |
| 流式响应 | SSE/NDJSON 全链路流式，前端实时展示步骤进度 |

---

## 八、技术取舍

| 取舍 | 选择 | 代价 |
|------|------|------|
| 向量检索 | Qdrant + BGE（语义检索） | 需要额外部署 Qdrant 容器 |
| BM25 索引 | jieba + rank-bm25（内存） | 关键词级检索，同义词检索弱 |
| 数据持久化 | JSON 文件 + SQLite | 不支持并发写，大数据量时性能下降 |
| 服务通信 | HTTP REST（非消息队列） | 同步耦合，一个服务慢影响调用方 |
| LLM 调用 | urllib.request（非 SDK） | 不支持自动重试、流控、连接池 |
| 部署 | Docker Compose（非 K8s） | 不支持自动扩缩容 |

---

**文档版本历史**

| 版本 | 日期 | 修改内容 |
|-----|------|---------|
| V1.0 | 2026-05-27 | 初始版本 |
| V1.1 | 2026-05-27 | 删除安全设计和运维监控章节 |
| V1.2 | 2026-07-30 | 与实际实现对齐，修正技术栈 |
| V2.0 | 2026-08-07 | 全面重写，反映 Qdrant+BGE+BM25 混合检索、Skill 引擎、多智能体、本体分步构建、计时调度等最新实现 |
