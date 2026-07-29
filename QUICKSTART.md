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
# 终端6: API网关
cd java/api-gateway
mvn spring-boot:run

# 终端7: 基础管理服务
cd java/admin-service
mvn spring-boot:run
```

## 首次使用

### 1. 访问前端

打开浏览器访问 http://localhost:3000

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
lsof -i :8001
lsof -i :8080
```

关闭占用端口的进程，或修改 `docker-compose.yml` 中的端口映射。

### Q: 前端无法访问API？

A: 检查API网关是否正常运行：

```bash
curl http://localhost:8080/api/status
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
bash scripts/start.sh
```

## 下一步

- 阅读完整的 [README.md](README.md)
- 查看 [PRD.md](PRD.md) 了解系统设计
- 根据需要修改配置
- 开始使用系统

---

**有问题？查看文档或联系开发团队！**
