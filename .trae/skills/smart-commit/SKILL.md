---
name: "smart-commit"
description: "自动审查工作区变更并三分类（应提交/应忽略/待用户决定），编写通俗中文提交信息自动 commit，以工作日志汇报改动，询问是否拉取远程，拉取后讲解远程变更、辅助合并并推送。当用户说“智能提交”“提交代码”“commit”等时调用。"
---

# 智能提交（Smart Commit）

面向多人远程协作项目的 Git 提交助手。调用本 skill 即代表用户已明确授权执行 git commit/pull/push，**无需再询问授权**；但每个决策点必须让用户知情，拿不准的必须询问用户。

## 工作流程总览

```
收集变更 → 三分类 → 用户确认 → .gitignore 处理 → add → commit → 工作日志
        → 询问是否拉取远程 → [同意] fetch → pull → 讲解远程变更(带链接) → 辅助合并 → push
```

## 阶段 1：收集变更信息

在项目根目录依次执行（全部使用相对路径，禁止硬编码绝对路径）：

| 命令 | 目的 |
|------|------|
| `git status --short` | 查看所有改动（M/A/??/D） |
| `git diff --stat` | 改动规模概览 |
| `git diff` | 已跟踪文件的具体改动（逐处读懂改动意图） |
| `git diff --cached` | 暂存区内容（如有） |
| `git log --oneline -10` | 了解仓库提交信息风格 |
| `git branch -vv` | 当前分支与远程追踪关系 |
| `git remote -v` | 确认远程地址 |

同时阅读项目 `.gitignore`，掌握已被忽略的路径，避免重复添加规则。

## 阶段 2：变更三分类

对每个变更/新增文件，必须归入以下三类之一，**拿不准的一律归入 C 类**。

### A 类 —— 应提交
- 源码：`*.py` / `*.java` / `*.vue` / `*.ts` / `*.tsx` / `*.js` / `*.sh` / `*.ps1` / `*.yml` / `*.yaml`
- 配置类 JSON（非运行时数据）、依赖清单（`requirements.txt` / `pom.xml` / `package.json` / `package-lock.json`）
- 文档：`README.md`、`docs/`、`PRD.md`、方案文档
- 测试文件、`Dockerfile*`、`.gitignore`、`.gitattributes`
- 确定为种子/模板数据的文件（如 `python/ontology-service/data/` 下带特例规则的 seed 本体）

### B 类 —— 应加入 .gitignore（不提交）
- 构建产物：`dist/`、`target/`、`build/`、编译产物 `*.jar`（`drivers/*.jar` 除外）、`*.class`
- 依赖与虚拟环境：`node_modules/`、`venv/`、`.venv/`、`__pycache__/`
- 运行时生成数据：日志 `*.log`、`*.bak`、`*.empty_backup`、会话/历史 JSON、`data_backup_*` 备份目录
- 本地环境配置：`.env`、`*.local.*`、IDE 配置（`.idea/`、`.vscode/`、`settings.local.json`）
- 大文件/模型：`models/` 目录、矢量库、图片缓存、上传文件
- 服务自动生成的运行时数据（如 `python/ontology-service/data/build_jobs/`、`user_ontologies/`）

### C 类 —— 需要用户决定（不得擅自处理）
- 用途不明的新文件（`??` 且无法从内容判断用途）
- 可能含敏感信息的文件（密钥、token、密码、证书）
- 大型二进制文件（> 5MB，除非确认必须入库）
- 既像数据又像种子/模板的文件（与 A 类判断冲突时）
- 与现有 `.gitignore` 规则相抵触的文件
- 删除类变更（`D`），必须确认是否误删

## 阶段 3：确认与执行提交

1. **向用户展示三分类清单**（表格：文件 → 类别 → 判断理由），明确询问 C 类处理方式，确认 A/B 类无误后才继续。
2. 处理 B 类：将未覆盖的忽略路径追加到 `.gitignore`。追加前先 Grep 确认无重复规则，追加时写中文注释说明原因。
3. 精确暂存：**禁止 `git add -A` / `git add .`**，必须按文件名逐个添加：
   ```powershell
   git add <file1> <file2> ...
   ```
4. 编写 commit message（见下）。
5. 执行 `git commit -m "..."`（信息较长可用 heredoc）。

### commit message 编写规范
- 风格对齐仓库最近提交（先观察 `git log --oneline -10`，如 `feat:` / `fix:` / `refactor:` / `docs:` / `chore:`）。
- **通俗易懂**：一句话说清"做了什么 + 为什么"，避免堆砌技术细节，让不熟悉该模块的队友也能看懂。
- 必须与真实改动对应，禁止夸大或编造。
- 多模块改动可用简短 body 分点说明（中文）。

## 阶段 4：工作日志汇报

提交完成后，以工作日志形式简要汇报：

```
【工作日志】YYYY-MM-DD HH:mm
提交：<commit 短 hash>（前 7 位）
变更内容：一两句话概括本次改动解决的问题/新增的能力
涉及文件：列出主要文件
.gitignore 调整：如有则列出新增规则
下一步：询问是否拉取远程代码
```

## 阶段 5：询问是否拉取远程

用 AskUserQuestion 提供选项：拉取远程并推送 / 仅提交不拉取 / 取消操作。

## 阶段 6：拉取远程、讲解、合并、推送（用户同意后）

1. `git fetch origin`。
2. 对比本地与远程：
   - 远程新增：`git log --oneline HEAD..origin/<分支>`
   - 本地领先：`git log --oneline origin/<分支>..HEAD`
3. 拉取：
   - 本地无新提交：`git pull`。
   - 本地有新提交（含刚 commit 的）：优先 `git pull --rebase`，保持线性历史。
   - **若产生冲突：禁止自动保留任何一方**。必须展示冲突文件，用 `git diff` 把冲突双方（`<<<<<<< HEAD` 本地 vs `>>>>>>>` 远程）完整列出，让用户选择保留哪方/如何合并，用户确认后执行 `git add <文件>` + `git rebase --continue`（或 `git merge --continue`）。
4. **通俗讲解远程变更**：
   - 用 `git log --oneline` 列出远程新增提交，逐条说明"改了什么、解决什么问题"。
   - 用 `git show <hash>` 查看具体改动，**以 file:/// 链接 + 行号范围**定位变更来源（格式：`[文件名](file:///绝对路径#L起-止)`；链接仅用于展示定位，命令本身仍用相对路径）。
   - 说明**变更前后效果**：变更前是什么行为/限制 → 变更后是什么行为/能力。
5. **辅助合并**：确认远程代码与本地未提交改动无冲突后继续；若有冲突先提醒用户暂存或提交后再合并。
6. **推送**：
   - `git branch -vv` 确认分支追踪关系：有 → `git push`；无 → `git push -u origin <分支>`。
   - 推送成功后报告结果；如生成了 MR/PR 链接一并附上。

## 硬性约束（违反即失败）

1. **全程相对路径**；所有 git 命令在项目根目录执行；禁止在命令中硬编码 `d:\code\...` 等绝对路径（多人协作项目，各环境不同）。
2. **禁止 `git add -A` / `git add .`**，必须逐个文件精确暂存。
3. **git pull 冲突时禁止自动丢弃任何一方**，必须两版俱陈、由用户选择。
4. 追加 `.gitignore` 前先检查是否已有匹配规则，禁止重复添加。
5. 不提交敏感信息（密钥/token/密码）；发现 C 类敏感文件必须先询问。
6. push 前用 `git branch -vv` 核对分支与远程追踪关系，禁止误推到未确认分支。
7. 变更分类拿不准时一律归入 C 类询问用户，不要自作主张。

## 常见场景速查

| 场景 | 处理 |
|------|------|
| 出现 `data_backup_*`、`*.bak` 目录 | B 类，追加 gitignore |
| 新增 `.vue`/`.py` 页面或接口 | A 类，正常提交 |
| 出现 `llm_config.json`、`.env` | B 类（已有规则则直接忽略） |
| 大模型权重 / 向量库文件 | B 类 |
| 不确定用途的 `??` 文件 | C 类，询问用户 |
| 删除的文件 | 确认是否误删后 `git add <该文件>` 精确暂存删除 |
| 远程有冲突提交 | 展示双版本，用户选择后 `git rebase --continue` |
