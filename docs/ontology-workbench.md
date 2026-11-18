# 动态本体：Ontosphere 原生工作台

动态本体直接集成 [Ontosphere 1.8.1](https://github.com/ThHanke/ontosphere/tree/6bdcb78b531b2300d047fbcdd10246fc62611cb9) 源码。编辑器和资源在本项目本地构建、同源运行。原 Vue/ECharts 仿制工作台已由真实 React/Reactodia 应用替换。

## 入口

- `/ontology`：创建或打开“装备协同推演”内置样例，不覆盖已保存的内容。
- `/ontology/library`：原有本体管理、新建、AI 构建、手工构建和模板。
- `/ontology/:id`：原生编辑器。构建任务 `?jobId=` 保留原只读预览。

保留原项目的侧边工具栏、原生节点卡片、属性编辑、关系创建、撤销重做、ABox/TBox、六种布局、Louvain/Label Propagation/K-Means 聚类、折叠层级、图例、缩略图、文件导入导出、SPARQL、SHACL、Konclude WASM、推理报告与诊断工具。顶部增加本系统的保存和版本记录，底部可以回放四个回合。

界面统一采用智能评估系统的蓝白配色，主色 `#3b82f6`、页面底色 `#f8fafc`、卡片白色、分割线 `#e2e8f0`。工具栏、原生编辑菜单、设置面板、推理报告、提示、中文使用文档均接入中文。Reactodia 使用完整中文语言包；上游动态界面文本与无障碍标签由嵌入层语言目录本地化，查询语句、用户输入、资源标识与 RDF 字面量保持原始数据。侧栏加宽至 56 像素以适配中文名称。主应用 Element Plus 同时设置为中文。

AI relay、外部本体和 workflow catalog 仍需相应外部服务配置，嵌入模式默认关闭自动远程加载。项目自己的 AI 构建接口继续保留。

## 装备协同推演

内置样例包含 14 个类、8 台装备、2 个协作小组、3 个协作单元、3 项任务和 4 个回合；回合 0 有 210 条断言、20 个实例，后续回合累积事件和时间节点。旧版本的默认标签在载入时显示为新名称，原始快照和用户自定义标签保留。

| 回合 | 时刻 | 事件 | 就绪率 | 协同度 | 任务进度 |
| --- | --- | --- | --- | --- | --- |
| 0 | 09:00 | 初始编组 | 100% | 82 | 8% |
| 1 | 09:15 | 状态变化，R-02/G-02 链路延迟 | 75% | 68 | 32% |
| 2 | 09:30 | 协同处理，G-02 维护 | 88% | 86 | 67% |
| 3 | 09:45 | 推演复盘 | 100% | 93 | 100% |

就绪装备定义为 `Platform AND (status hasValue "就绪")`；具备就绪装备的编组由 `hasPlatform SOME ReadyPlatform` 推导。还包括传递隶属、互逆的调度关系与装备编配关系。实际 Konclude OWL 2 DL 分类可在回合 0 得到 8 台就绪装备、3 个具备就绪装备的编组；回合 1 就绪装备减为 6 台。评估结果通过 `derivedFrom` 追溯到当前事件。SHACL 检查装备状态、0–100 的整数任务进度和评估事件来源。

切换回合加载为草稿并清理旧推导事实；保存后形成新的版本。已有草稿切换前会提示，历史版本也先载入草稿。示例首次提供可读的固定布局，后续保存的用户布局优先。

## 保存与兼容

项目保存先提交 Reactodia 暂存的编辑，再保存完整 N-Quads 多图数据集、RDF 断言、命名空间和 ABox/TBox 布局。原生画布的 Save、Ctrl/Cmd+S 与顶部“保存本体”接入同一后端。SHA-256 修订号防止并发覆盖（409）；保存前保留最近 50 次历史快照。

断言 RDF 为权威来源，保留 OWL 限制、匿名节点、多继承、字面量语言和类型。`urn:vg:inferred`、shapes、workflow 与 provenance 图保留在数据集中，推导事实不会混入权威业务断言，重开后需重新推理。旧 v3 类型、实体和关系接口保留投影，相同 IRI 保留原 ID、来源、绑定及属性历史。旧服务修改投影时，缓存指纹失效，下一次编辑器读取会重建 RDF，防止加载过期副本。

在原版 WASM 的中文值联调中发现 U+FFxx 字节扩展和旧 `rdf:PlainLiteral` 输出问题；本地兼容层只修复与断言输入精确匹配的编码值，并统一为 RDF 1.1 字面量，避免中文状态损坏和 SHACL 误报。说明及第三方许可位于 `frontend/ontosphere/ASSESSMENT-INTEGRATION.md`、`LICENSE` 和 `upstream.json`。

## API

前端统一通过 `/api` 代理。

| 方法与路径 | 用途 |
| --- | --- |
| POST `/ontology/examples/wargame` | 幂等创建并打开示例 |
| GET `/ontology/examples/wargame/turns/{0..3}` | 读取相应回合，业务数据不变 |
| GET `/ontology/{id}/workbench/editor` | 原生编辑器 RDF、修订号、布局 |
| PUT `/ontology/{id}/workbench/editor` | `{dataset, expected_revision, layouts, namespaces, note}` 保存 |
| POST `/ontology/{id}/workbench/editor/preview` | 历史快照转换为编辑器草稿 |
| GET `/ontology/{id}/workbench/history` | 最近 50 次保存前快照 |

原有 workbench 文档、OWL-RL、只读 SPARQL、SHACL、RDF 转换接口继续支持其他模块。原生编辑器直接使用浏览器中的 Konclude OWL 2 DL、Comunica SPARQL 与 SHACL 引擎。

## 构建与验证

```powershell
cd frontend
npm ci
npm --prefix ontosphere ci
npm run build
npm run dev
```

Node 20.19+ 或 22.12+；当前本地 Node 24。`build` 自动构建原生应用到 `frontend/public/ontosphere/`，再构建 Vue 应用到 `frontend/dist/`，生成的 WASM 与 Worker 资源无需远程 CDN。仅调整上游编辑器时可执行 `npm run build:ontology`。

Konclude 需要 `SharedArrayBuffer`。Vite 开发/预览和 `docker/nginx.conf` 已配置 COOP `same-origin`、COEP `credentialless`；生产通过 HTTPS 或本地 localhost 访问。编辑器 iframe 同源，消息桥核验 origin 和 parent window。

```powershell
cd python/ontology-service
../../.venv/Scripts/python.exe -m unittest discover -s tests
cd ../../frontend/ontosphere
npm run typecheck
npx vitest run src/integration/koncludeLiterals.test.ts
cd ..
npm run test:workbench
```

浏览器验收使用真实服务与原版编辑器，覆盖 ABox/TBox、OWL 分类、SHACL、回合切换清理推导、节点修改、保存后重开、现有本体查询与知识库全文入口。截图输出到 `tmp/ontology-ui/`。构建与浏览器测试顺序执行，避免主项目自动组件声明生成造成测试中途 HMR。
