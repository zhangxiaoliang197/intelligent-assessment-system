# 快速开始指南

## 环境检查

在开始之前，请确保已安装以下软件：

- MySQL 8.x
- PowerShell 7（Windows 一键启动时使用）
- Docker & Docker Compose（仅 Docker 部署时需要）
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

## 方式一：Docker快速启动（推荐）

### 1. 克隆项目

```bash
cd /path/to/projects
git clone <repository-url> intelligent-assessment-system
cd intelligent-assessment-system
```

### 2. 构建镜像

```bash
docker-compose build
```

### 3. 启动服务

QA 与 Admin 之间通过内部令牌读取大模型密钥。Docker 模式必须先设置一个随机且仅后端可见的令牌：

```bash
# Linux / macOS
export ADMIN_INTERNAL_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
```

```powershell
# Windows PowerShell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes); $rng.Dispose()
$env:ADMIN_INTERNAL_TOKEN = ([BitConverter]::ToString($bytes)).Replace('-', '')
docker compose up -d
```

同一次部署中的 `qa-service` 与 `admin-service` 必须使用相同令牌。不要把令牌提交到 GitHub；本地 `start.ps1` 会自动生成并保存在已忽略的 `.runtime/admin-internal-token` 中。

```bash
docker compose up -d
```

### 4. 验证服务

```bash
docker-compose ps
```

所有服务启动后，访问：

- 前端界面: http://localhost:10086
- QA / Skills API: http://localhost:10253
- 基础管理 API: http://localhost:10258

## 方式二：本地开发模式

### Windows 一键启动（推荐）

在项目根目录使用 PowerShell 7：

```powershell
pwsh -File .\setup.ps1   # 首次运行或环境变化后执行
pwsh -File .\start.ps1
```

启动成功后访问 <http://localhost:10086>。停止全部服务：

```powershell
pwsh -File .\stop.ps1
```

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

# 终端4: 独立评估服务（QA Service 已承载 Skills 流式编排）
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

### 5. 配置并执行 Skills 顺序查询

1. 在“基础管理”中确认数据库状态为“已连接”，并为需要查询的物理表创建数据集。
2. 进入“评估分析”，选择数据源，点击“配置 Skills”。
3. 为每一步选择数据集并填写查询指令；系统严格按从上到下的顺序执行。
4. 对依赖上一步的步骤启用“依赖前序”，并配置：
   - **依赖失败策略**：停止流程、跳过本步或受限继续。
   - **要求结果非空**：避免 SQL 虽成功但业务目标未满足仍被判为成功。
   - **空结果策略**：继续、标记跳过或停止流程。
5. 保存并选择 Skill，输入最终评估问题后发送。

右侧“Skills 执行流程”会展示数据集发现、结构读取、指标加载、SQL 生成、依赖校验、数据集范围校验、SQL 执行和最终汇总。失败、空结果、跳过和截断都会显示明确终态。

Skills 保存在管理数据库的 `ass_evaluation_skill` 表中，不再依赖单进程本地 JSON；重新启动服务或刷新页面后仍可继续使用。生产环境应给业务数据源配置最小权限的只读数据库账号。

## 常见问题

### Q: 服务启动失败怎么办？

A: 检查端口占用情况：

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 10086,10252,10253,10254,10255,10256,10258
```

关闭占用端口的进程，或修改 `docker-compose.yml` 中的端口映射。

### Q: 前端无法访问API？

A: 检查前端代理依赖的 QA 和管理服务是否正常运行：

```powershell
Invoke-RestMethod http://localhost:10253/health
Invoke-RestMethod http://localhost:10258/actuator/health
```

### Q: 如何查看日志？

```bash
# Docker模式
docker-compose logs -f <service-name>

# 本地模式
# 查看终端输出
```

### Q: 如何重启服务？

```bash
docker-compose restart <service-name>
```

## 下一步

- 阅读完整的 [README.md](README.md)
- 查看 [PRD.md](PRD.md) 了解系统设计
- 根据需要修改配置
- 开始使用系统

---

**有问题？查看文档或联系开发团队！**
