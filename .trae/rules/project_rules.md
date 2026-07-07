# 智能评估系统 - 本地启动规则

## 核心原则
- **"启动本地服务" = 直接在终端运行命令，无需沙箱测试**
- Python/前端可在沙箱启动，Java 编译和启动必须在用户本地终端

## Docker 镜像生成规则（重要！）
- **禁止逐个修复逐个生成镜像**。镜像用于向内网拷贝，频繁生成浪费用户时间
- **每轮修改完成后，一次性检查、一次性生成全量镜像**
- 生成前必须逐项确认：
  1. `git pull` 或代码修改后，diff 中所有 Java/Python/前端文件都审查过
  2. 所有跨服务调用 URL（`os.getenv` / `@Value` / 容器名）与 `start-docker-run.sh` 的 `-e` 对照通过
  3. `vite.config.ts` 代理目标端口与 Python 服务端口一致
  4. Gateway 控制器中的容器名与 `start-docker-run.sh` 的 `--name` 一致
  5. `.sh` / `.json` / `.py` / `.yml` 换行符为 LF（`.gitattributes` 已配置）
  6. 所有受影响的服务 JAR/dist 都已重新编译，**然后一次性** `docker build + save` 全部 9 个镜像

## 本机环境
| 工具 | 路径 | 备注 |
|------|------|------|
| JDK 17 | `C:\Program Files\Java\jdk-17` | JAVA_HOME 必须指向此路径 |
| Maven | `C:\tools\apache-maven-3.9.9\bin\mvn` | 不在 PATH 中，需完整路径 |
| Node.js | `D:\Program Files\nodejs` | 前端/Vite 用 |
| Python | PATH 中的 python | 需安装 fastapi/uvicorn/sklearn/docx/lxml |
| MySQL 5.5 | 端口 3306 | 用户 root，密码 1025 |
| Git | `D:\Program Files\Git\bin` | GitHub 认证 token 已配置 |

## 编译 Java 服务 (首次/代码更新后)
```powershell
$env:JAVA_HOME = "C:\Program Files\Java\jdk-17"
C:\tools\apache-maven-3.9.9\bin\mvn package -DskipTests -q  # 先后在 admin-service 和 api-gateway 目录下执行
```

## 启动全部 9 个服务

### Python 服务 (6个) - 沙箱可执行
```powershell
$r="d:\TRAE SOLO\result\intelligent-assessment-system"
Start-Process python -ArgumentList "-u main.py" -WorkingDirectory "$r\python\<service>" -WindowStyle Hidden
```
服务列表: knowledge(10252), qa(10253), indicator(10254), evaluation(10255), ontology(10256), solution-evaluation(10259)

### Java 服务 (2个) - 用户终端执行
```powershell
# 必须用 javaw + 完整绝对路径，Program Files 中的空格用反引号转义
C:\Program` Files\Java\jdk-17\bin\javaw -jar "d:\TRAE SOLO\result\intelligent-assessment-system\java\admin-service\target\admin-service-1.0.0.jar"
C:\Program` Files\Java\jdk-17\bin\javaw -jar "d:\TRAE SOLO\result\intelligent-assessment-system\java\api-gateway\target\api-gateway-1.0.0.jar"
```

### 前端 - 沙箱可执行
```powershell
Start-Process "D:\Program Files\nodejs\npx.cmd" -ArgumentList "vite --host" -WorkingDirectory "d:\TRAE SOLO\result\intelligent-assessment-system\frontend" -WindowStyle Hidden
```

## 常见问题速查
| 问题 | 原因 | 解决 |
|------|------|------|
| `无效的标记: --release` | JAVA_HOME 指向 JDK 8 | `$env:JAVA_HOME="C:\Program Files\Java\jdk-17"` |
| `mvn 不是命令` | Maven 不在 PATH | 用 `C:\tools\apache-maven-3.9.9\bin\mvn` |
| Java 启动后闪退 | `Start-Process java` 不兼容 / 用了 JDK 8 | 用 `javaw` + 绝对路径 |
| `Access denied (MySQL)` | MySQL 密码错误 | 默认密码是 `1025` |
| `application.yml` | MySQL 默认密码已改为 1025 | `${MYSQL_PASSWORD:1025}` |

## Docker 跨服务调用环境变量映射 (start-docker-run.sh)

所有跨服务 URL 通过 `os.getenv` 获取（默认 localhost），Docker 启动时用 `-e` 覆盖为容器名：

| 容器 | 需要的环境变量 | 目标容器 | start-docker-run.sh 状态 |
|------|---------------|----------|--------------------------|
| assessment-qa | `ADMIN_SERVICE_URL` | assessment-admin:10258 | ✅ |
| assessment-qa | `KNOWLEDGE_SERVICE_URL` | assessment-knowledge:10252 | ✅ |
| assessment-indicator | `QA_SERVICE_URL` | assessment-qa:10253 | ✅ |
| assessment-indicator | `ADMIN_SERVICE_URL` | assessment-admin:10258 | ✅ |
| assessment-solution-evaluation | `QA_SERVICE_URL` | assessment-qa:10253 | ✅ |
| assessment-solution-evaluation | `INDICATOR_SERVICE_URL` | assessment-indicator:10254 | ✅ |
| assessment-solution-evaluation | `ADMIN_SERVICE_URL` | assessment-admin:10258 | ✅ |
| assessment-solution-evaluation | `COMBAT_QUERIES_PATH` | /app/queries-custom.json (卷挂载) | ✅ |
| assessment-knowledge | (无) | — | — |
| assessment-evaluation | (无) | — | — |
| assessment-ontology | (无) | — | — |
| assessment-admin | `MYSQL_HOST/PORT/...` | 外部 MySQL | ✅ |
| assessment-gateway | (无) | — | — |
| assessment-frontend | (nginx 反向代理) | 容器名 | ✅ |

**规则：新增跨服务调用时，必须在 start-docker-run.sh 中补上对应的 -e 环境变量。**
