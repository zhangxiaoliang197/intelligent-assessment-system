# 智能评估系统 - 本地启动规则

## 核心原则
- **"启动本地服务" = 直接在终端运行命令，无需沙箱测试**
- Python/前端可在沙箱启动，Java 编译和启动必须在用户本地终端

## 工作纪律（必须遵守！）
严格按以下阶段顺序执行，禁止跳步：

```
1. 开发功能（可以改代码、写文件）
       ↓
2. 用户确认功能没问题
       ↓
3. 用户给出"编译"/"打包"/"生成镜像"指令 → 才执行编译+打包
       ↓
4. 用户确认镜像没问题
       ↓
5. 用户给出"提交"/"commit"/"push"指令 → 才执行 git commit + push
```

- **禁止修改完代码后自行编译、自行打包镜像、自行 git commit/push**
- **禁止 git pull 产生冲突时自动保留本地代码而丢弃远程代码**。冲突必须列出两个版本让用户选择
- **打包镜像前必须确认所有受影响的服务都已重新 compile，禁止用旧 JAR/dist 打新镜像**

## Docker 镜像生成规则（重要！）
- **禁止逐个修复逐个生成镜像**。镜像用于向内网拷贝，频繁生成浪费用户时间
- **禁止修改完代码后自行编译或生成镜像**。必须等用户给出"编译"/"生成镜像"/"打包"等明确指令后才能执行
- **每轮修改完成后，一次性检查、一次性生成全量镜像**
- 生成前必须逐项确认：
  1. `git pull` 或代码修改后，diff 中所有 Java/Python/前端文件都审查过
  2. 所有跨服务调用 URL（`os.getenv` / `@Value` / 容器名）与 `start-docker-run.sh` 的 `-e` 对照通过
  3. `vite.config.ts` 代理目标端口与 Python 服务端口一致
  4. nginx.conf 反向代理中的容器名与 `start-docker-run.sh` 的 `--name` 一致
  5. `.sh` / `.json` / `.py` / `.yml` 换行符为 LF（`.gitattributes` 已配置）
  6. 所有受影响的服务 JAR/dist 都已重新编译，**然后一次性** `docker build + save` 全部 8 个镜像（含 Qdrant）
  7. **Java 服务必须 commit 之后、打包之前重新 compile**。严格顺序: 改代码→commit→编译JAR→docker build。禁止用旧JAR打包新镜像



## 编译 Java 服务 (首次/代码更新后)
前提：JDK 17 与 Maven 已加入系统 PATH（start.ps1 会通过 Get-Command 自动发现，禁止硬编码绝对路径）。
```powershell
# 在 admin-service 目录下执行；若 mvn 不在 PATH，请先将其 bin 目录加入 PATH
mvn package -DskipTests -q
```

## 启动全部 7 个服务

推荐直接运行 `.\start.ps1`直接启动项目，报错查看日志分析
> 注意：start.ps1 必须保存为 UTF-8 with BOM，否则 PowerShell 5 解析中文注释会报错。

### Python 服务 (5个) - 沙箱可执行
```powershell
$r="d:\code\intelligent-assessment-system"
Start-Process python -ArgumentList "-u main.py" -WorkingDirectory "$r\python\<service>" -WindowStyle Hidden
```
服务列表: knowledge(10252), qa(10253), indicator(10254), evaluation(10255), ontology(10256)

### Java 服务 (1个) - 用户终端执行
推荐直接运行 `.\start.ps1`（自动发现 JDK/Maven/Node/Qdrant，并按 LOG_ENV 注入 SPRING_PROFILES_ACTIVE）。
手动启动时用 Get-Command 动态发现工具路径（禁止硬编码绝对路径）：
```powershell
$javaExe = (Get-Command java).Source      # 或用 javaw.exe：与 java.exe 同目录
$jar = "d:\code\intelligent-assessment-system\java\admin-service\target\admin-service-1.0.0.jar"
Start-Process -FilePath $javaExe -ArgumentList "-jar `"$jar`"" -WorkingDirectory "d:\code\intelligent-assessment-system"
```
> 注意：Spring profile 由 start.ps1 从 LOG_ENV 推导注入；手动启动时需自行 `$env:SPRING_PROFILES_ACTIVE="dev"`（或 prod），否则 logback 落到 default profile 无文件日志。

### 前端 - 沙箱可执行
```powershell
$nodeBin = Split-Path (Get-Command node).Source
Start-Process "$nodeBin\npx.cmd" -ArgumentList "vite --host" -WorkingDirectory "d:\code\intelligent-assessment-system\frontend" -WindowStyle Hidden
```

## 常见问题速查
| 问题 | 原因 | 解决 |
|------|------|------|
| `无效的标记: --release` | JAVA_HOME 指向 JDK 8 | 确认 `Get-Command java` 指向 JDK 17，重装或修正 PATH |
| `mvn 不是命令` | Maven 不在 PATH | 确认 `Get-Command mvn`，未安装请装 Maven 并将 bin 加入 PATH |
| Java 启动后闪退 | `Start-Process java` 不兼容 / 用了 JDK 8 | 用 `javaw` + 绝对路径 |
| `Access denied (MySQL)` | MySQL 密码错误 | 密码通过 .env 或环境变量配置，application.yml 默认值为 root |
| `application.yml` | MySQL 密码配置 | `${MYSQL_PASSWORD:root}`，实际值通过 .env 或环境变量覆盖 |

## Docker 跨服务调用环境变量映射 (start-docker-run.sh)

所有跨服务 URL 通过 `os.getenv` 获取（默认 localhost），Docker 启动时用 `-e` 覆盖为容器名：

| 容器 | 需要的环境变量 | 目标容器 | start-docker-run.sh 状态 |
|------|---------------|----------|--------------------------|
| assessment-qa | `ADMIN_SERVICE_URL` | assessment-admin:10258 | ✅ |
| assessment-qa | `KNOWLEDGE_SERVICE_URL` | assessment-knowledge:10252 | ✅ |
| assessment-indicator | `QA_SERVICE_URL` | assessment-qa:10253 | ✅ |
| assessment-indicator | `ADMIN_SERVICE_URL` | assessment-admin:10258 | ✅ |
| assessment-indicator | `KNOWLEDGE_SERVICE_URL` | assessment-knowledge:10252 | ✅ |
| assessment-indicator | `EVALUATION_API_URL` | assessment-qa:10253 | ✅ |
| assessment-knowledge | (无) | — | — |
| assessment-evaluation | (无) | — | — |
| assessment-ontology | (无) | — | — |
| assessment-admin | `MYSQL_HOST/PORT/...` | 外部 MySQL | ✅ |
| assessment-frontend | (nginx 反向代理) | 容器名 | ✅ |

**规则：新增跨服务调用时，必须在 start-docker-run.sh 中补上对应的 -e 环境变量。**

---

# 代码编写规范

## 一、注释语言规范（强制）
- 所有注释、docstring、函数说明、代码注释必须使用中文
- 变量名、函数名、类名、文件名使用英文（驼峰命名）
- 日志输出、错误信息、API 响应消息使用中文

```python
# ✅ 中文注释
def _classify_query(query: str) -> str:
    """先调用 qa-service 的 LLM 分类接口，失败则用关键词兜底。"""

# ❌ 英文注释
def process_data(data):
    """Process the input data."""  # 必须用中文
```

## 二、Python 规范

### 2.1 Docstring 格式
- 使用 Google 风格 docstring
- 类/函数必须有 docstring，说明功能、参数、返回值
- 复杂逻辑必须有行内注释

### 2.2 命名规范
- 模块名：`snake_case.py`
- 类名：`PascalCase`
- 函数名：`snake_case`
- 变量名：`snake_case`
- 常量名：`UPPER_SNAKE_CASE`（在 config.py 中定义）

### 2.3 日志
- 统一使用各服务的 `logging_config.py`（JSON 结构化输出，字段与 Java logback 对齐），禁止自定义日志格式
- 通过环境变量配置：`LOG_ENV` / `LOG_LEVEL` / `LOG_DIR`
- message 必须中文：
```python
logger.info("指标分析完成，共分析 {count} 个指标")
logger.warning("知识库检索超时，使用本地缓存")
logger.error(f"数据库连接失败: {e}")
```

### 2.4 错误处理
```python
try:
    result = http_post(url, data)
except Exception as e:
    logger.error(f"调用 {url} 失败: {e}")
    # 返回统一错误格式
    return {"success": False, "message": f"调用服务失败: {str(e)}"}
```

## 三、Java 规范

### 3.1 Javadoc 格式
- 类、公共方法必须有 Javadoc 注释，使用中文
- 包含 `@param`、`@return`、`@throws`（如适用）

### 3.2 命名规范
- 包名：`com.assessment.<service>.<module>`
- 类名：`PascalCase`
- 方法名：`camelCase`
- 变量名：`camelCase`
- 常量名：`UPPER_SNAKE_CASE`（`static final`）

### 3.3 API 响应格式
- 统一返回 `ResponseEntity<Map<String, Object>>`
- 成功：`{"success": true, ...}`
- 失败：`{"success": false, "message": "中文错误信息"}`

## 四、Vue/TypeScript 规范

### 4.1 注释约定
- 复杂逻辑分段使用 `// ── 标题 ──` 分隔；组件 props、emit 必须有中文注释

### 4.2 命名规范
- 组件名：`PascalCase.vue`（如 `Layout.vue`）
- 变量名：`camelCase`
- 常量名：`UPPER_SNAKE_CASE`（局部常量）
- 组合式函数：`useCamelCase()`（如 `useSpeechRecognition`）

### 4.3 组件结构
```vue
<template>
    <!-- 模板内容 -->
</template>

<script setup lang="ts">
// 1. 导入（第三方 → 内部 → 样式）
import { ref, computed } from 'vue'

// 2. 组合式函数调用
const { isListening, start, stop } = useSpeechRecognition()

// 3. 响应式变量
const inputMessage = ref('')

// 4. 计算属性
const isDisabled = computed(() => !inputMessage.value.trim())

// 5. 方法定义
async function sendMessage() {
    // 发送消息逻辑
}
</script>

<style scoped>
/* 样式 */
</style>
```

### 4.4 错误提示
- `ElMessage` / API 错误提示必须中文

## 五、通用规范

### 5.1 API 统一格式
所有后端 API 返回必须遵循：
```json
{
    "success": true/false,
    "message": "中文提示信息",
    "data": {}  // 业务数据
}
```

### 5.2 禁止硬编码
- 禁止硬编码 URL、端口、密码
- 使用环境变量或配置文件（`os.getenv` / `@Value`）
- 常量定义在 `config.py` / `application.yml` 中

### 5.3 错误信息
- 面向用户的错误信息必须中文，保留英文异常堆栈用于调试

### 5.4 接口文档
- FastAPI 自动生成文档，title/description 使用中文
- Java Controller 使用 `@Api` 注解时描述使用中文

### 5.5 跨服务调用
- 使用环境变量获取目标服务 URL
- 添加超时时间（建议 5-30 秒）
- 添加异常捕获和降级处理

---

> **说明**：本规范文件（`.trae/rules/project_rules.md`）会被 AI 自动读取，作为编程时的参考。同时建议在项目根目录添加 `CONTRIBUTING.md` 供人类开发者参考。
