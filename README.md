# 智能评估系统

**Intelligent Assessment System**

面向作战场景的智能评估平台，集成了知识库管理、本体模型构建、智能问答、指标分析、评估分析等多种能力。

## 📋 项目简介

本系统是面向作战场景的智能评估平台，旨在为军事指挥、作战决策、效能评估等关键环节提供智能化支持。系统集成了知识库管理、本体模型构建、智能问答、指标分析、评估分析等多种能力，通过统一的数据底座实现跨系统的数据共享和协同工作。

## 🎯 核心功能

### 工具模块
- **智能问答** - 基于RAG知识库的智能问答系统
- **指标分析** - 智能分析评估指标体系，支持树状图展示
- **评估分析** - 评估方案的构建与管理

### 辅助系统
- **知识库** - 知识的上传、解析、分类和检索管理
- **本体模型** - 本体构建与知识图谱展示
- **基础管理** - 数据库配置、数据集管理、指标管理、大模型配置

## 🏗️ 技术架构

### 前端技术栈
- Vue 3 + Vite
- Element Plus
- ECharts
- TypeScript

### 后端技术栈

#### AI服务 (Python)
- FastAPI
- LangChain
- ChromaDB

#### 业务服务 (Java)
- Spring Boot 3.x
- MyBatis-Plus

### 数据存储
- MySQL - 元数据库（数据库配置、数据集、指标、大模型配置等）
- JSON 文件 - Python 服务的业务数据持久化（知识库、本体模型、会话记录等，原子写入 + .bak 备份）
- 业务数据源 - 通过 admin-service 的 JDBC 动态连接，支持 MySQL/PostgreSQL/Oracle/达梦 V8/SQL Server

### 动态本体模块（palantir/）
- 独立子系统 AEGIS（Palantir 动态本体），技术栈：.NET 10 + Neo4j + OpenSearch + Redis，代码位于 `palantir/` 目录
- 入口：智能评估系统「本体模型」页面顶部「动态本体」卡片，点击在新标签页打开（默认 `http://localhost:3000`）
- 与宿主系统解耦：独立端口（5000/3000/7474/7687/9200/6379）、独立网络、独立数据卷
- 维护说明：`palantir/` 为整目录独立维护模块，含自有 `docker-compose.yml`、Dockerfile、种子数据

## 🚀 快速开始

### 环境要求
- Node.js 18+
- Python 3.11+
- Java 17+
- Docker & Docker Compose

### 安装部署

#### 1. 克隆项目
```bash
git clone <repository-url>
cd intelligent-assessment-system
```

#### 2. 前端安装
```bash
cd frontend
npm install
npm run dev
```

#### 3. Python服务
```bash
cd python/knowledge-service
pip install -r requirements.txt
python main.py
```

#### 4. Java服务
```bash
cd java/admin-service
mvn spring-boot:run
```

### Docker部署

Linux / macOS：

```bash
bash deploy/build-images.sh
bash scripts/start.sh
```

Windows PowerShell 构建：

```powershell
.\build-all.ps1
```

`scripts/start.sh` 会以当前镜像强制重建容器，并验证 QA 健康检查与
30 个内置 Skill。更新镜像后不要使用 `docker compose restart`，该命令
仍会复用旧容器。

态势图模块另含 30 个面向地图与图表编排的专业 Skill，支持搜索、分类、
智能推荐、收藏、执行计划预检、自定义 Skill 新建/编辑，并通过 `skillId`
进入态势生成流程。评估分析与态势图的 `SKILL.md` 对所有可见用户开放在线
编辑；源码克隆默认使用各服务自身的 `data` 目录，Docker 则使用持久化卷，
不依赖开发者机器上的绝对路径。

#### 一键启动（智能评估系统 + 动态本体模块）

Windows PowerShell：

```powershell
.\start-all.ps1            # 使用已有镜像启动全部服务
.\start-all.ps1 -Build     # 重新构建全部镜像后启动（首次使用）
```

- 脚本统一拉起宿主的 9 个服务与 AEGIS 的 5 个服务，并自动灌入 AEGIS 种子数据（幂等）
- AEGIS 手动灌数据：`Invoke-RestMethod -Uri http://localhost:5000/api/seed -Method Post`
- 动态本体前端地址可用 `VITE_AEGIS_URL` 环境变量覆盖（frontend 构建时读取）

## 📁 项目结构

```
intelligent-assessment-system/
├── frontend/                    # 前端项目
│   ├── src/
│   │   ├── pages/              # 页面组件
│   │   ├── components/         # 通用组件
│   │   ├── router/             # 路由配置
│   │   ├── stores/             # 状态管理
│   │   └── services/           # API服务
│   └── package.json
├── python/                      # Python AI服务
│   ├── knowledge-service/       # 知识库服务
│   ├── qa-service/             # 智能问答服务
│   ├── indicator-service/      # 指标分析服务
│   ├── evaluation-service/      # 评估分析服务
│   └── ontology-service/        # 本体模型服务
├── java/                        # Java业务服务
│   └── admin-service/          # 基础管理服务（数据库配置/数据集/指标/大模型配置/SQL执行）
├── docker/                      # Docker配置
├── scripts/                    # 部署脚本
├── docker-compose.yml          # Docker Compose配置（智能评估系统）
├── docker-compose.aegis.yml    # Docker Compose合并编排（include palantir/）
├── start-all.ps1               # 统一启动脚本（含 AEGIS 种子灌入）
└── README.md
```

```
palantir/                       # 动态本体模块（AEGIS，整目录独立维护）
├── src/backend/Aegis.API/     # .NET 10 后端
├── src/frontend/              # Vue 3 前端
├── data/                      # 种子数据（seed.cypher / intel_documents.json）
├── ontology/                  # 本体定义文件
└── docker-compose.yml         # AEGIS 自有编排（被根目录 include 引入）
```

## 🎨 功能演示

### 门户页面
- 统一的系统入口
- 智能工具快捷入口
- 辅助系统导航

### 知识库
- 多格式文档上传（PDF、Word、Excel等）
- 自动解析和向量化
- 分类和标签管理
- 全文检索

### 本体模型
- 可视化知识图谱
- 实体和关系管理
- 本体构建和编辑

### 指标分析
- 指标树状图展示
- 分层指标体系
- 算法详情

### 基础管理
- 数据库驱动管理（支持 MySQL/PostgreSQL/Oracle/达梦 V8/SQL Server 多数据库动态加载驱动）
- 数据集配置
- 评估指标管理
- 大模型参数配置

## 🔧 配置说明

### 数据库配置
- **元数据库**：MySQL（存储数据库配置、数据集、指标、大模型配置等元数据，由 admin-service 管理）
- **业务数据源**：通过 admin-service 的 JDBC 动态连接，支持以下数据库：
  - MySQL
  - PostgreSQL
  - Oracle
  - 达梦数据库 V8
  - SQL Server

### 大模型配置
支持本地部署的大模型：
- Qwen（通义千问）
- ChatGLM（智谱）
- LLaMA
- Baichuan（百川）

## 📊 系统特点

1. **微服务架构** - 各模块独立部署，灵活扩展（共 7 个服务：1 前端 + 5 Python + 1 Java）
2. **统一数据底座** - 知识库、本体模型、数据共享
3. **多智能体协同** - Orchestrator 编排 + 专项 Agent + 兜底降级，兼顾专业性与灵活性
4. **Text-to-SQL 管线** - 智能选表 → LLM 生成 SQL → 安全校验 → 执行 → 分析，全链路打通
5. **Skill 系统** - 内置可扩展的技能目录，支持自定义技能注册与运行时管理
6. **智能选表机制** - 打分精选最多 5 张表，降低 Token 消耗与幻觉率
7. **离线部署** - 支持内网私有化部署，无外部中间件依赖
8. **可配置性** - 每个服务支持独立配置，通过环境变量覆盖

## 📝 开发说明

### 前端开发
```bash
cd frontend
npm install
npm run dev
```

### 后端开发

#### Python服务
```bash
cd python/knowledge-service
pip install -r requirements.txt
uvicorn main:app --reload
```

#### Java服务
```bash
cd java/admin-service
mvn spring-boot:run
```

## 📄 许可证

本项目仅供内部使用，禁止外传。

## 👥 开发团队

智能评估系统开发团队

## 📧 联系方式

如有问题，请联系开发团队。
