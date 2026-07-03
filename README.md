# 智能评估系统

**Intelligent Assessment System**

面向作战场景的智能评估平台，集成了知识库管理、本体模型构建、智能问答、指标分析、方案评估等多种能力。

## 📋 项目简介

本系统是面向作战场景的智能评估平台，旨在为军事指挥、作战决策、效能评估等关键环节提供智能化支持。系统集成了知识库管理、本体模型构建、智能问答、指标分析、方案评估等多种能力，通过统一的数据底座实现跨系统的数据共享和协同工作。

## 🎯 核心功能

### 工具模块
- **智能问答** - 基于RAG知识库的智能问答系统
- **指标分析** - 智能分析评估指标体系，支持树状图展示
- **方案评估** - 评估方案的构建与管理

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
- PostgreSQL - 关系型数据库
- Neo4j - 图数据库
- ChromaDB - 向量数据库

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
```bash
docker-compose up -d
```

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
│   ├── evaluation-service/      # 方案评估服务
│   └── ontology-service/        # 本体模型服务
├── java/                        # Java业务服务
│   ├── admin-service/          # 基础管理服务
│   └── api-gateway/            # API网关
├── docker/                      # Docker配置
├── scripts/                    # 部署脚本
├── docker-compose.yml          # Docker Compose配置
└── README.md
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
- 数据库驱动管理（支持达梦数据库V8.1）
- 数据集配置
- 评估指标管理
- 大模型参数配置

## 🔧 配置说明

### 数据库配置
系统支持多种数据库：
- MySQL
- PostgreSQL
- Oracle
- 达梦数据库V8.1
- SQL Server

### 大模型配置
支持本地部署的大模型：
- Qwen（通义千问）
- ChatGLM（智谱）
- LLaMA
- Baichuan（百川）

## 📊 系统特点

1. **微服务架构** - 各模块独立部署，灵活扩展
2. **统一数据底座** - 知识库、本体模型、数据共享
3. **离线部署** - 支持内网私有化部署
4. **可配置性** - 每个服务支持独立配置

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
