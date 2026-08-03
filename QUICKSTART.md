# 快速开始指南

## 环境检查

在开始之前，请确保已安装以下软件：

- Docker & Docker Compose
- Node.js 18+
- Python 3.11+
- Java 17+
- Maven 3.6+

检查版本：

```bash
docker --version
docker-compose --version
node --version
python --version
java -version
mvn --version
```

## 环境变量配置（重要）

本系统通过 `.env` 文件集中管理所有配置（数据库连接、服务地址、大模型密钥等）。

### 1. 创建 .env 文件

项目根目录下已提供模板 `.env.example`，复制一份即可：

```bash
# Linux / macOS
cp .env.example .env

# Windows PowerShell / CMD
copy .env.example .env
```

### 2. 填写必填项

打开 `.env`，至少需要配置以下内容：

| 变量 | 用途 | 是否必填 |
|------|------|---------|
| `MYSQL_PASSWORD` | MySQL 数据库密码 | **必填**（如无密码则保持为空） |
| `LLM_API_KEY` | 大模型 API 密钥 | **必填** |
| `MYSQL_HOST` | MySQL 主机地址 | 默认 `localhost`，按需修改 |

如果使用远程 MySQL，还需要修改 `MYSQL_HOST`、`MYSQL_PORT` 等连接参数。

### 3. 注意事项

- `.env` 已被 `.gitignore` 忽略，**不会提交到 Git**，避免密码泄露
- 修改 `.env` 后需要**重新启动**对应服务才能生效
- 如果通过 Docker 部署，`start-docker-run.sh` 会自动读取 `.env` 并注入容器
- 其他所有变量保持默认值即可，无需修改

---

## 方式一：Docker快速启动（推荐）

### 1. 克隆项目

```bash
cd /path/to/projects
git clone <repository-url> intelligent-assessment-system
cd intelligent-assessment-system
```

### 2. 构建镜像

Linux / macOS：

```bash
bash deploy/build-images.sh
```

Windows PowerShell：

```powershell
.\build-all.ps1
```

### 3. 启动服务

```bash
bash scripts/start.sh
```

### 4. 验证服务

```bash
curl -fsS http://127.0.0.1:10253/health
curl -fsS http://127.0.0.1:10253/evaluation/skills
```

所有服务启动后，访问：

- 前端界面: http://localhost:10086
- Skill 目录接口: http://localhost:10253/evaluation/skills

> `docker compose restart` 只会重启旧容器，不会应用刚加载或刚构建的
> 新镜像。更新后请运行 `bash scripts/start.sh`，脚本会强制重建容器并
> 校验 30 个内置 Skill。

## 方式二：本地开发模式

### 前端开发

```bash
cd frontend
npm install
npm run dev
```

### Python服务开发

在不同的终端窗口中启动各个Python服务：

```bash
# 终端1: 知识库服务
cd python/knowledge-service
pip install -r requirements.txt
python main.py

# 终端2: 智能问答服务
cd python/qa-service
pip install -r requirements.txt
python main.py

# 终端3: 指标分析服务
cd python/indicator-service
pip install -r requirements.txt
python main.py

# 终端4: 评估分析服务
cd python/evaluation-service
pip install -r requirements.txt
python main.py

# 终端5: 本体模型服务
cd python/ontology-service
pip install -r requirements.txt
python main.py
```

### Java服务开发

```bash
# 终端6: 基础管理服务
cd java/admin-service
mvn spring-boot:run
```

## 首次使用

### 1. 访问前端

打开浏览器访问 http://localhost:10086

### 2. 配置大模型

1. 进入"基础管理"页面
2. 选择"大模型配置"标签
3. 填写API地址和密钥
4. 保存配置

### 3. 上传知识

1. 进入"知识库"页面
2. 点击"上传知识"按钮
3. 选择要上传的文档
4. 等待解析完成

### 4. 开始使用

- 在门户页面选择工具
- 使用智能问答功能
- 分析指标体系
- 构建评估方案

## 常见问题

### Q: 服务启动失败怎么办？

A: 检查端口占用情况：

```bash
# 检查 Python 服务端口（示例：knowledge-service 10252）
lsof -i :10252
# 检查 Java 服务端口（admin-service 10258）
lsof -i :10258
# 检查前端端口
lsof -i :10086
```

关闭占用端口的进程，或修改 `docker-compose.yml` 中的端口映射。

### Q: 前端无法访问API？

A: 检查后端服务是否正常运行：

```bash
# 检查 admin-service 健康状态
curl http://localhost:10258/actuator/health
# 检查 qa-service 是否响应
curl -fsS http://127.0.0.1:10253/health
```

### Q: 如何查看日志？

系统采用统一日志体系，所有服务输出 JSON 结构化日志，区分开发/生产环境。

#### 日志环境变量

在 `.env` 文件中配置（参见 `.env.example` 的"统一日志配置"部分）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_ENV` | `dev` | `dev`=彩色控制台+DEBUG 文件；`prod`=JSON+INFO 按日轮转 |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARN/ERROR） |
| `LOG_RETENTION_DAYS` | `14` | 生产环境日志保留天数 |
| `LOG_MAX_SIZE_MB` | `100` | 单文件最大体积（按大小轮转时生效） |

#### 日志文件位置

**本地开发**（`LOG_ENV=dev`，默认）：

```
项目根/logs/
├── knowledge-service/app.log
├── qa-service/app.log
├── indicator-service/app.log
├── evaluation-service/app.log
├── ontology-service/app.log
└── admin-service/app.log
```

> qa-service 的 SQL 调试日志仍在 `python/qa-service/logs/sql_gen.log`。

**Docker 生产**（`LOG_ENV=prod`）：

```
/opt/intelligent-assessment/logs/{service}/app.log
```

#### 查看日志

```bash
# Docker模式 - 实时查看容器日志（JSON 格式）
docker compose logs -f qa-service

# Docker模式 - 查看持久化日志文件
tail -f /opt/intelligent-assessment/logs/qa-service/app.log

# 本地模式 - 实时查看日志文件
tail -f logs/qa-service/app.log

# 本地开发 - 终端直接显示彩色输出（LOG_ENV=dev 时）

# Java admin-service - 指定生产 profile 启动查看 JSON 日志
$env:SPRING_PROFILES_ACTIVE="prod"; mvn spring-boot:run
```

#### 日志格式说明

生产环境每行日志为 JSON 对象，字段包括：

```json
{
  "timestamp": "2026-08-03 10:00:00,000",
  "level": "INFO",
  "service": "qa-service",
  "logger": "qa-service",
  "message": "统一日志已初始化",
  "module": "main",
  "line": 23,
  "thread": "MainThread",
  "process": 1234
}
```

> 此 JSON 格式可直接被 ELK/Loki 等集中式日志系统解析，未来升级无需改代码。

### Q: 如何重启服务？

```bash
bash scripts/start.sh
```

## 下一步

- 阅读完整的 [README.md](README.md)
- 查看 [PRD.md](PRD.md) 了解系统设计
- 根据需要修改配置
- 开始使用系统

---

**有问题？查看文档或联系开发团队！**
