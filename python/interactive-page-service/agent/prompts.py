"""ipage-service 提示词集合。

三类提示词：
1. 规划（Planner，function-calling 大纲）
2. 取数（Researcher，单数据集 Text-to-SQL）
3. 页面（PageWriter，受限运行时契约下的单文件 HTML 生成 / 重写 / 重新设计）

页面运行时 API 手册（RUNTIME_API_GUIDE）必须与前端 public/vendor/page-kit.js
的实现严格一致；改动任一侧都必须同步另一侧。
"""
from typing import Any, Dict, List

from agent import dimension_graph

# ──────────────────────────────────────────────────────────────────
# 数据集目录格式化
# ──────────────────────────────────────────────────────────────────

def format_meta_catalog(meta: Dict[str, Any]) -> str:
    """把 /export/for-llm 的元数据格式化为 Planner 可读的数据集目录文本。"""
    if not isinstance(meta, dict) or not meta.get("success"):
        return "（数据集目录暂不可用）"
    data = meta.get("data", {}) or {}
    schemas = data.get("schemas", []) or []
    if not schemas:
        return "（当前没有任何已注册且可用于分析的数据集）"

    blocks: List[str] = []
    for idx, schema in enumerate(schemas, 1):
        if not isinstance(schema, dict):
            continue
        ds_id = schema.get("datasetId") or schema.get("id") or ""
        name = schema.get("name") or schema.get("tableName") or ds_id
        table = schema.get("tableName") or ""
        desc = schema.get("description") or schema.get("businessMeaning") or ""
        fields = schema.get("fields") or schema.get("columns") or []
        field_lines = []
        geo_lng_fields = set()
        geo_lat_fields = set()
        for f in fields:
            if not isinstance(f, dict):
                continue
            col = f.get("name") or f.get("column") or f.get("fieldName") or ""
            ctype = f.get("type") or f.get("dataType") or ""
            comment = f.get("businessMeaning") or f.get("comment") or f.get("label") or ""
            field_lines.append(f"    - {col} {ctype} {comment}".rstrip())
            low = str(col).lower()
            if low.endswith("_lng") or low in ("lng", "lon", "longitude"):
                geo_lng_fields.add(str(col))
            if low.endswith("_lat") or low in ("lat", "latitude"):
                geo_lat_fields.add(str(col))
        geo_tag = ""
        if (geo_lng_fields and geo_lat_fields) or any(dimension_graph.annotated_geo_pair(schema)):
            # 注解声明的坐标列（如"经度/纬度"）也算有地理能力，避免非约定命名被误判
            geo_tag = "  【地理能力：有坐标字段】"
        block = [f"{idx}. 数据集ID: {ds_id}｜名称: {name}｜表: {table}{geo_tag}"]
        if desc:
            block.append(f"   说明: {desc}")
        if field_lines:
            block.append("   字段:")
            block.extend(field_lines[:60])
            if len(field_lines) > 60:
                block.append(f"    - ……其余 {len(field_lines) - 60} 个字段略")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def format_schema_for_sql(schema: Dict[str, Any]) -> str:
    """物理表结构 → SQL 生成提示文本。"""
    lines = [f"表名: {schema.get('tableName', '')}"]
    for f in schema.get("fields", []) or []:
        lines.append(
            f"- {f.get('column', '')} {f.get('type', '')} {f.get('comment', '')}".rstrip()
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# 1) Planner
# ──────────────────────────────────────────────────────────────────

PLANNER_SYSTEM_SUFFIX = """
【当前阶段：页面规划（Planner）】
你是态势分析与交互页面设计专家。根据用户问题与下方可用数据集目录，调用 emit_page_plan 工具提交规划。

先做意图识别：
- intent=data_page：用户需要基于业务数据做态势分析、统计、分布、趋势、地图展示、目标/威胁/任务研判等；
- intent=general：闲聊、通用问答、概念解释、与数据集无关的计算等。此时 subQuestions/sections 留空数组，
  并在 directAnswer 中用中文直接回答。

data_page 规划要求：
1. subQuestions 至少 1 个，每个 datasetId 必须来自目录；问题之间互不重复，分别支撑页面的一个信息面；
2. mode=aggregate 用于图表/统计（SQL 可 GROUP BY 聚合）；mode=detail 用于地图航迹/标点、明细表格，
   需要逐行数据，必须保留全部业务列；
3. 需要地图时，按数据集语义选择地理形态（该数据集必须有成对经纬度字段，否则 geo=none）：
   - tracks：逐点航迹/轨迹表（含实体编号、序号 seq、记录时间，如敌我双方航迹明细），运行时自动按实体+任务串线；
   - points：单位/事件位置（飞机基地、雷达/导弹阵地、威胁点、打击/侦察/战损事件位置、目标点分布等），
     运行时自动按单位类别绘制象形符号并配图例；
   - circles：静止目标/阵地的固定范围圈表（行内自带半径列，圆心固定不动，如防空阵地、雷达站的覆盖范围）；
     一表含多根半径列时（如探测半径 + 打击半径），运行时会按列名各自成圈
     （探测/侦察为虚线圈、打击为实线圈），并在圆心绘制阵地/目标符号，无需再单独规划 points 子问题；
     注意：若需求是"打击/侦察范围随飞机移动、随航迹动态变化"，不要用 circles，
     应规划航迹表并声明 geo=tracks（半径由机型档案的侦察/打击半径在运行时自动匹配）；
   一个态势综合页面可同时为航迹表与单位/事件表分别规划 geo 子问题（地图区块可引用多个子问题数据）；
4. sections 描述页面区块顺序，kind 只能取 kpi/chart/map/text/table/filters/timeline；
   一般至少包含：1 个 kpi 区、2 个以上 chart（目录数据确实支持时）、1 个 text 结论区；
   有地理数据且问题与空间态势相关时安排 map；有明细数据时可安排 table；
5. 标题与目的中不得出现目录里不存在的字段值或具体数字（数据源无关）；
6. 若问题含时间条件（如"近一周""某月某日"），在对应 subQuestion.filters 中写明字段与边界
   （{"时间字段": {"gte": "起始", "lte": "结束"}}），且只能使用目录中真实存在的时间字段；
7. 问题中的分类/类型/状态/阵营/名称等实体词（如某类对象、某种状态、某个名称）由系统自动
   解析为跨表过滤，不要在 subQuestion.filters 中编造本表不存在的分类列或外键 ID 条件；
   filters 只写本表真实存在的字段条件（如时间边界）。

直接调用 emit_page_plan 工具，不要输出额外文本。

可用数据集目录：
"""


def build_plan_messages(query: str, catalog_text: str, parent_query: str = "",
                        skill_context: Dict[str, Any] = None) -> list:
    """Planner 消息列表。

    skill_context 为空（未命中技能）时，消息与改造前完全一致。
    """
    context_line = f"承接上文：{parent_query}\n" if parent_query else ""
    guide = format_skill_plan_guide(skill_context)
    return [
        {"role": "system",
         "content": PLANNER_SYSTEM_SUFFIX + (("\n" + guide) if guide else "") + catalog_text},
        {"role": "user", "content": f"{context_line}用户问题：{query}"},
    ]


def build_replan_messages(feedback: str, catalog_text: str,
                          parent_plan: Dict[str, Any],
                          skill_context: Dict[str, Any] = None) -> list:
    """修订场景的「延续式」规划消息。

    修订必须在父页面已有取数口径上延续：已有子问题原样沿用（系统直接继承已取到的
    数据、不重复查询），只为修改意见带来的新数据需求追加子问题。否则「加入飞行轨迹」
    这类取数需求在只换呈现的修订链路上永远无法生效。
    """
    import json
    existing = [
        {
            "id": sq.get("id"), "datasetId": sq.get("datasetId"),
            "question": sq.get("question"), "mode": sq.get("mode"),
            "geo": sq.get("geo", "none"),
        }
        for sq in (parent_plan.get("subQuestions") or []) if isinstance(sq, dict)
    ]
    existing_text = json.dumps(existing, ensure_ascii=False, indent=2)
    guide = format_skill_plan_guide(skill_context)
    return [
        {"role": "system",
         "content": PLANNER_SYSTEM_SUFFIX + (("\n" + guide) if guide else "") + catalog_text},
        {"role": "user", "content":
            f"这是对已生成页面的修订。用户修改意见：{feedback}\n\n"
            f"上一版规划中已取数的子问题（系统会直接继承其数据，不会重复查询）：\n{existing_text}\n\n"
            "延续式规划要求：\n"
            "1. 上列已有子问题若仍能满足需求，必须原样沿用：id、datasetId、question、mode、geo "
            "均不得改动（包括问题措辞），改动会导致该子问题被重新取数；\n"
            "2. 只有当修改意见确实需要新的数据维度（如新增飞行轨迹/时间序列/新的分类统计）时，"
            "才追加新子问题，id 依次为 q3、q4…（不得与已有 id 重复），datasetId 必须来自数据集目录；\n"
            "2.1 需要航迹/动态演示时，选择含实体编号、序号、记录时间与成对经纬度的航迹表，"
            "并声明 geo=tracks（页面开启 playback 即可让能力范围圈随飞机移动）；"
            "只有需要静止阵地/目标的固定范围圈时才声明 geo=circles（表须有半径字段）；\n"
            "3. sections 可按修改意见重新组织，但 ref 只能引用最终存在的子问题 id；"
            "新增航迹/时间序列时相应增加 map 区块（引用航迹子问题）与 timeline 区块；\n"
            "4. 其余规划要求（区块数量、结论区、地理形态与坐标字段匹配等）保持不变。\n\n"
            "请调用 emit_page_plan 提交完整规划（含沿用的全部子问题与新增子问题）。"},
    ]


# ──────────────────────────────────────────────────────────────────
# 2) Researcher：Text-to-SQL
# ──────────────────────────────────────────────────────────────────

def build_sql_messages(question: str, schema: Dict[str, Any], mode: str,
                       scope_hint: Dict[str, list] = None) -> list:
    """单数据集只读 SELECT 生成提示。

    scope_hint: 系统经实体解析确认的本表过滤范围 {列名: [允许值]}，
    提示 LLM 在 WHERE 中遵循（仅提示，服务端会做确定性行级兜底过滤）。
    """
    scope_text = ""
    if scope_hint:
        clauses = []
        for col, values in scope_hint.items():
            if not values:
                continue
            literals = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values[:500])
            clauses.append(f"{col} IN ({literals})")
        if clauses:
            scope_text = (
                "\n系统已确认的过滤范围（生成 WHERE 时必须遵循，禁止放宽或忽略；"
                "下列列均为本表真实列）：\n" + "\n".join("- " + c for c in clauses) + "\n"
            )
    if mode == "detail":
        rules = (
            "1. 只能生成一条 SELECT，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE；\n"
            "2. 表名列名严格来自下方表结构；明细保真：禁止聚合/GROUP BY/DISTINCT，"
            "SELECT 全部业务列（经纬度、名称、时间、高度、速度、状态等都要保留）；\n"
            "3. 可按问题生成 WHERE 精确过滤与 ORDER BY（航迹按实体、时间/序号排序）；\n"
            "4. 时间边界 {gte:A, lte:B} 必须生成 列 >= A AND 列 <= B，不得用当前时间替代历史时点；\n"
            "5. 标准 ANSI SQL；不要加 LIMIT（行数由后端统一控制）。"
        )
    else:
        rules = (
            "1. 只能生成一条 SELECT，禁止写操作；\n"
            "2. 表名列名严格来自下方表结构；\n"
            "3. 统计问题用 WHERE + 聚合(COUNT/SUM/AVG/MAX/MIN) + GROUP BY，"
            "分组结果必须覆盖全部类目/时段，ORDER BY 合理排序；\n"
            "4. 聚合列与分组列满足 GROUP BY 规则，不得混入未聚合明细列；\n"
            "5. 饼图类占比查询分类数控制在 8 个以内（小类可归并为「其他」）；\n"
            "6. 时间边界 {gte:A, lte:B} 必须生成 列 >= A AND 列 <= B；\n"
            "7. 标准 ANSI SQL；不要加 LIMIT。"
        )
    return [
        {"role": "system", "content":
            "【当前阶段：取数】你是 SQL 生成专家。根据问题与单个数据集的表结构，"
            "生成一条精确的只读 SELECT。仅返回 JSON：{\"sql\": \"SELECT ...\"}，无其它文字。\n"
            "规则：\n" + rules},
        {"role": "user", "content":
            f"分析问题：{question}\n取数模式：{mode}\n{scope_text}\n表结构：\n{format_schema_for_sql(schema)}"},
    ]


# ──────────────────────────────────────────────────────────────────
# 3) PageWriter：受限运行时契约
# ──────────────────────────────────────────────────────────────────

RUNTIME_API_GUIDE = """
【页面运行时契约（只能使用下列 API，禁止直接使用 echarts/L 底层对象）】

页面是单文件 HTML，数据不在 HTML 里，而在运行时由系统注入。你的 <script> 中必须且只能
通过一个启动入口拿到数据：

    SitApp.bootstrap(function (data) {
        // data 结构：
        // data.question           用户问题
        // data.datasets = [ {id, name, purpose, mode, columns, rows, truncated, totalRows,
        //                     geo, geoFeatures, summary} ]
        //   - mode='aggregate'：rows 已是聚合后的小结果集（图表直接用）
        //   - mode='detail'   ：rows 为明细行（地图/表格用），运行时行数可能比下方样例多，代码按完整数据编写
        //   - geoFeatures     ：mode='detail' 时预整形的地图数据 {tracks, units, points, circles}，
        //                       直接传给 SitMap，无需自己从 rows 解析坐标
        // data.generatedAt        数据生成时间
    });

一、SitChart.render(el, spec) —— 图表（推荐用高层 spec，自动套专业配色/提示框/图例/自适应）
    el 可用选择器字符串或 DOM 元素；spec：
    {
      type: 'bar'|'line'|'pie'|'radar'|'scatter',
      title: '图表标题',
      xData: ['一月','二月'],              // 类目轴（bar/line）
      series: [ {name:'蓝方', data:[1,2]}, {name:'红方', data:[3,4]} ],
      stack: false,                        // 可选，是否堆叠
      horizontal: false,                   // 可选，条形图
      showDataZoom: false,                 // 可选，类目很多时开启缩放滑块
      yName: '架次',                        // 可选
      percent: false                       // 可选，按百分比堆叠展示
    }
    饼图：series 只给一个 [{name, data:[{name:'类别', value:10}]}]
    雷达：spec = {type:'radar', title, indicators:['维度A','维度B'], series:[{name:'蓝方',data:[80,90]}]}
    散点：spec = {type:'scatter', title, series:[{name, data:[[x,y],...]}]}
    返回 chart 对象（一般无需持有）。容器 div 必须有明确高度（CSS 给高度，如 .ip-card 内 320px）。

二、SitMap.render(el, spec) —— 地图（瓦片/坐标系/符号/图例全部由运行时处理）
    地理数据来自每个 detail 数据集的 geoFeatures（见数据说明），把需要上图的数据集合并后传入：
    spec：
    {
      center: [120.2, 24.5] | 'auto',      // 不传默认自动适配
      zoom: 6,
      // 单位/事件点：优先使用 geoFeatures.units（与 points 同构，运行时按 unitKind 自动绘制
      // 飞机/基地/雷达/导弹/目标/设施/事件等象形符号并生成图例；未知类型自动用圆点兜底）
      // 数据源注解可额外给出（三者均为可选，缺省时运行时按类型自动推断，页面直接透传即可）：
      //   symbol      象形符号注册表键（运行时优先使用）
      //   factionColor 该阵营的规范色 #rrggbb（运行时优先用于符号/航迹/范围圈配色）
      //   statusKey   状态规范键 destroyed|miss|critical|heavy|light（运行时据此画角标/叉）
      units:   [{lng, lat, name, unitKind:'aircraft'|'base'|'threat'|'target'|'facility'
                       |'event_strike'|'event_damage'|'event_recon'|'other',
                 faction:'蓝方'|'红方'|'', type, status, time, props:{...},
                 symbol?, factionColor?, statusKey?}],
      // 航迹：一条 track 是一个架次；points 已按时间排序，含 time/alt/speed/heading
      // 半径是装备固有定值（可能为空）：reconRadiusKm 侦察半径、strikeRadiusKm 打击半径，
      // 开启 playback 后运行时据此画出"圆心随飞机走"的动态能力圈；此时整条航迹不预画，
      // 由播放器绘制飞机图标并让已飞航迹渐进显示（见下方"三、时间轴回放"）
      tracks:  [{id, name, faction:'蓝方'|'红方'|'', category, missionId,
                 strikeRadiusKm, reconRadiusKm, symbol?, factionColor?,
                 points:[{lng, lat, seq, time, alt, speed, heading, props:{}}]}],
      // 静态能力范围圈（坐标固定、半径定值，如阵地/威胁圈）：faction/rangeType 用于配色与图例
      // 一表多半径（探测 + 打击）会各自成圈；圆心处的单位符号由运行时一并绘制
      circles: [{lng, lat, radiusKm: 120, name, faction:'蓝方'|'红方'|'',
                 rangeType:'打击范围'|'侦察范围', kind:'strike'|'recon'|'other',
                 factionColor?}],
      // 时间轴回放（可选）：有带 time 的航迹时强烈建议开启，播放器与动态能力圈由运行时接管
      playback: { enabled: true, radius:'both'|'strike'|'recon', trail: true, speed: 1, showBar: true }
    }
    多数据集上图：遍历 data.datasets，把各 ds.geoFeatures 的 units/tracks/circles 分别 concat 后传入；
    同一数据集 geoFeatures.units 不存在时回退使用 points。
    返回 mapApi：
      mapApi.on('featureClick', function(f){ /* f={kind:'unit'|'track'|'circle', name, faction, props} */ });
      mapApi.flyTo(lng, lat, zoom);
      mapApi.highlight(function(f){ return f.faction === '红方'; });   // 联动高亮
      mapApi.playback.play() / pause() / toggle() / seek(0~1) / reset();
      mapApi.playback.on(function(s){ /* s={index,total,ratio,time,playing} */ });
    坐标一律用 WGS84 经纬度（数据集里的原始坐标），运行时按底图自动转换。

    **地图视图自动锁定**：同一容器反复调用 SitMap.render（如时间轴播放轨迹）时，
    运行时会**自动保留用户的缩放/拖动视图**，不会因数据变化而重新 fitBounds。因此：
    - 时间轴播放时**不要**每次 render 都传 center，也**不要**在播放循环中调用 flyTo；
    - 仅在确实需要把地图定位到特定坐标（如点击某架飞机聚焦）时，才传 center 或调用 flyTo；
    - 首次渲染不传 center 会自动适配到全部数据范围（开启 playback 时已把半径计入）。

三、时间轴回放（SitMap 内置，禁止自己实现播放器）
    地图数据中存在带 time 的航迹时，直接给 SitMap 传 spec.playback，运行时自动完成：
    1. 注入播放条：播放/暂停、进度拖动、完整时间标签（YYYY-MM-DD HH:MM:SS）、
       倍速按钮（0.5×/1×/2×/4× 循环切换）、重置；
    2. **不预画整条航迹**：开启 playback 后整条航迹折线、起点标记与终点图标全部由播放器
       接管，地图上只出现飞机图标（按机型象形符号、机头朝当前航向）；
    3. 按当前时刻在航迹点上线性插值出每架飞机的位置，飞机图标随播放移动；同时把
       "起点→当前位置"的已飞航迹逐步画出（飞机到哪航迹显示到哪），未飞到的航段不出现；
       拖动进度条回退时航迹随之缩短，重置回起点时只剩飞机图标、无航迹线；
    4. 以飞机当前位置为圆心、以 strikeRadiusKm / reconRadiusKm 为半径画动态能力圈
       （侦察虚线、打击实线），圆心随飞机运动；
    5. 对已飞航段生成扫掠走廊（圆扫过的覆盖范围）留痕，从起飞累积到当前时刻、
       随播放推进增长（拖动回退随之收缩），重置时清空，不预展示全程；
    6. 多架次真实日期分散在多个自然日时，运行时自动按"日内归一化"把全部航迹叠加到
       同一虚拟日演示；播放条时间按"虚拟基准日（取时间轴最早真实日期）+ 日内时刻"显示
       完整年月日时分秒，航迹弹窗等业务展示仍是真实日期（数据不篡改）；
    7. 当前时刻早于首点（未出动）或晚于末点（已返航）的架次不显示飞机图标、不留航迹、
       不画圈不留带，已画出的图层即时消失——任何时刻都是"有多少在空飞机就有多少圈"；
    8. 带 time 的事件类点（unitKind 为 event_strike / event_damage / event_recon）按各自的
       "事件时刻"出现、此后常显：当前时刻早于该事件时刻时它不在图上，拖动回退或重置时
       重新隐藏；单位、阵地等非事件点即使带 time 也始终常显。事件时刻会并入时间轴，
       因此晚于全部航迹末点的事件也能等到自己的时刻。若希望某类点一开始就全程常显，
       就不要给它填 time 字段。
    **严禁**再自己写 setInterval 播放循环、自己写滑块、自己画航迹折线与飞机图标、
    自己过滤航迹点重渲染地图——那样图标不会随飞机移动、航迹不会渐进显示，且不同页面
    表现不一致。需要自定义控件时只调用 mapApi.playback.* 并订阅其事件
    （事件参数 s={index,total,ratio,time,playing,speed}），不要重新调用 SitMap.render。

四、SitBus —— 组件联动事件总线
    SitBus.on('filter', function(payload){ ... });
    SitBus.emit('filter', {faction:'蓝方'});
    筛选器/Tab 变化时 emit，KPI 与所有图表的渲染函数订阅后用筛选后的数据重算重绘。

五、SitUtil / SitTable —— 工具
    SitUtil.esc(s)                 HTML 转义（拼 innerHTML 时必须用）
    SitUtil.fmtInt(n)              千分位整数
    SitUtil.fmtNum(n, digits)      固定小数位
    SitUtil.fmtPct(n, digits)      百分比（n 为 0-1 或 0-100 自动识别）
    SitUtil.groupBy(rows, key)     -> {类别: [行]}
    SitUtil.sum(rows, key) / avg(rows, key) / countBy(rows, key)
    SitUtil.unique(rows, key)      去重值列表
    SitTable.render(el, {columns:[{key,label}], rows, pageSize:10})  带分页的明细表

六、SitApp 其它
    SitApp.reportError(msg)        页面内业务异常可上报（父界面据此提示，不影响其它区块）
"""

PAGE_SYSTEM_HEADER = """
【当前阶段：页面生成（PageWriter）】
你是资深的数据可视化工程师与军用态势大屏设计师。你将收到：用户问题、页面规划、数据包结构与样例行。
你的任务：输出一个完整、专业、可交互的单文件 HTML 页面（中文界面），把数据中的事实讲清楚。

设计要求：
1. 专业态势风格：浅色版面、克制配色（主色深蓝 #1d4ed8，强调红 #dc2626 / 橙 #d97706 / 绿 #059669），
   卡片化布局（可用注入的 .ip-card/.ip-title/.ip-kpi 等基础类，也可自定义 <style>）；
   页眉含页面标题、用户问题、生成时间（data.generatedAt）与数据来源说明；
   【阵营颜色自动映射】图表系列名称含"红方""蓝方"时，运行时会自动将"红方"渲染为红色(#dc2626)、
   "蓝方"渲染为蓝色(#1d4ed8)，无需在 spec 中指定 color；series 顺序可任意，颜色不随顺序变化；
   地图航迹的 faction 字段同样自动上色；**数据项自带 factionColor 时以它为准**（数据源注解
   已算出规范色，直接透传即可，不要自行覆盖）；其它系列按专业配色自动分配；
2. 布局用 CSS Grid/Flex 响应式：KPI 卡片横排；图表 2 列（窄屏自动 1 列）；
   地图给足高度（建议 420-520px）；结论区放页面底部；
3. 图表选型匹配数据：比较/排名用 bar，时间趋势用 line，占比（≤8 类）用 pie，
   多维能力对比用 radar，两数值维度分布用 scatter；每个图表有中文标题与一句话结论（可放卡片下方）；
4. 可交互：如果数据含阵营/类别/时间等维度，提供筛选按钮或下拉并通过 SitBus 联动
   KPI、图表、地图（地图用 mapApi.highlight）；有航迹数据时须给 SitMap 传 spec.playback，
   由运行时提供播放条（含 0.5×/1×/2×/4× 倍速）、"飞机图标随播放移动 + 航迹渐进显示 +
   能力圈随飞机移动"的动态演示，不要自己写播放器、不要自己画航迹折线；
   至少让页面上的关键控件真正生效，禁止摆设按钮；
5. KPI 必须用 SitUtil 从 data.datasets 的 rows 实时计算（如总数、平均值、分类计数），
   不得硬编码任何数字；所有数字、名称只能来自数据包，严禁编造；数据为空的区块显示
   「暂无相关数据」空态，不得留白或造假；
6. 每个图表/地图容器必须有明确高度；脚本在拿到数据后渲染，并做必要的空值与类型保护；
7. 只允许一个业务 <script>；禁止 <script src>、外链 CDN、<link>、<iframe>、
   fetch/XMLHttpRequest/WebSocket/eval/new Function/localStorage/document.cookie；
   禁止直接操作 echarts 与 L 全局对象，一切渲染走 SitChart/SitMap/SitTable；
8. 代码健壮：rows 可能比样例多/字段缺失/值为 null，须做防御；解析时间用字符串比较或 Date 构造均可；
9. 【篇幅约束】单页 HTML 目标不超过 3 万字符（含样式与脚本）。为控制篇幅：
   - 优先复用注入的 .ip-card/.ip-title/.ip-kpi 等基础类与 Sit* 组件，禁止重复内联同一样式；
   - 只保留必要的行内注释，禁止大段说明性注释与装饰性分隔；
   - 禁止把数据行复制进 HTML/脚本（数据一律从 SitApp.bootstrap 的 data 取）；
   - 若内容过多，合并同类区块、精简文案，优先保证页面结构完整（有闭合 </html>）；
10. 直接输出 <!DOCTYPE html> 开头的完整 HTML，不要 markdown 代码围栏、不要解释文字。
""" + RUNTIME_API_GUIDE


def _geo_features_view(geo: Dict[str, Any]) -> Dict[str, Any]:
    """geoFeatures 的省 token 视图：结构与真实数据一致，仅航迹点/单位点采样。

    运行时注入数据包中 geoFeatures 为全量，页面代码必须按全量编写。
    """
    if not isinstance(geo, dict):
        return {"tracks": [], "units": [], "points": [], "circles": []}
    tracks_view = []
    for tr in geo.get("tracks") or []:
        pts = tr.get("points") or []
        tracks_view.append({
            "id": tr.get("id"), "name": tr.get("name"),
            "faction": tr.get("faction", ""), "category": tr.get("category", ""),
            "missionId": tr.get("missionId", ""),
            "strikeRadiusKm": tr.get("strikeRadiusKm"),
            "reconRadiusKm": tr.get("reconRadiusKm"),
            "pointCount": len(pts),
            # 只展示首尾点样例，字段结构即运行时每点结构
            "firstPoint": pts[0] if pts else None,
            "lastPoint": pts[-1] if len(pts) > 1 else None,
        })
    units = geo.get("units") or geo.get("points") or []
    return {
        "tracks": tracks_view,
        "units": units[:8],
        "unitCount": len(units),
        "circles": (geo.get("circles") or [])[:8],
        "note": "运行时 geoFeatures 为全量数据（tracks 含全部 points、units 含全部点），此处为结构样例。",
    }


def _bundle_view(bundle: Dict[str, Any], sample_rows: int) -> Dict[str, Any]:
    """供 LLM 阅读的数据包视图：明细数据只给样例行 + 完整字段与总行数。"""
    view = {
        "question": bundle.get("question", ""),
        "generatedAt": bundle.get("generatedAt", ""),
        "datasets": [],
    }
    for ds in bundle.get("datasets", []):
        rows = ds.get("rows", []) or []
        entry = {
            "id": ds.get("id"),
            "name": ds.get("name"),
            "purpose": ds.get("purpose"),
            "mode": ds.get("mode"),
            "columns": ds.get("columns"),
            "totalRows": ds.get("totalRows", len(rows)),
            "truncated": ds.get("truncated", False),
            "geo": ds.get("geo", {"kind": "none"}),
            "geoFeatures": _geo_features_view(ds.get("geoFeatures")),
            "summary": ds.get("summary", ""),
            "rowsSample": rows[:sample_rows],
            "sampleNote": (
                f"运行时数据包将包含全部 {ds.get('totalRows', len(rows))} 行（字段与样例完全一致），"
                "请按完整数据编写代码，下方仅展示前若干行样例。"
                if ds.get("mode") == "detail" and len(rows) > sample_rows else ""
            ),
        }
        view["datasets"].append(entry)
    return view


def build_page_messages(query: str, plan: Dict[str, Any], bundle: Dict[str, Any],
                        sample_rows: int,
                        skill_context: Dict[str, Any] = None) -> list:
    """页面首次生成消息。

    skill_context 为空（未命中技能）时，消息与改造前完全一致。
    """
    import json
    sections = plan.get("sections", [])
    plan_text = json.dumps(
        {"title": plan.get("title", ""), "sections": sections,
         "interactions": plan.get("interactions", [])},
        ensure_ascii=False, indent=2,
    )
    bundle_text = json.dumps(
        _bundle_view(bundle, sample_rows), ensure_ascii=False, indent=2, default=str,
    )
    guide = format_skill_page_guide(skill_context)
    return [
        {"role": "system", "content": PAGE_SYSTEM_HEADER + (("\n" + guide) if guide else "")},
        {"role": "user", "content":
            f"用户问题：{query}\n\n页面规划：\n{plan_text}\n\n"
            f"数据包（结构+样例）：\n{bundle_text}\n\n"
            "请输出完整单文件 HTML。"},
    ]


def build_repair_messages(issues: List[str]) -> list:
    """Guard 校验失败后的重新生成消息（追加在首次生成消息之后）。

    不回灌上一版页面：历史实现只把页面截断到前 12000 字符（真实页面 40k~50k 字符），
    模型看到的是未闭合的半截文档，反而会照抄残缺结构。改为把校验问题作为硬约束重出。
    """
    return [
        {"role": "user", "content":
            "你上一版尝试生成的页面没有通过自动校验，存在以下问题：\n- "
            + "\n- ".join(issues)
            + "\n\n请重新生成一版完整 HTML，逐条规避上述问题（仍然遵守全部运行时契约），不要解释。"},
    ]


def build_redesign_messages(feedback: str) -> list:
    """带修改意见的重新设计消息（追加在首次生成消息之后）。

    不回灌旧页面 HTML：修订语义是「带着意见重新设计」，模型依据完整的数据包与规划
    重新组织呈现与交互；数据包已由 orchestrator 按意见增量补齐（含新增数据集）。
    """
    return [
        {"role": "user", "content":
            f"用户对当前版本提出修改意见：{feedback}\n\n"
            "这是对同一问题的重新设计，不是局部打补丁：\n"
            "1. 请忽略既有实现，按上述意见重新组织页面结构、图表选型与交互方式；\n"
            "2. 数据已按修改意见补齐（上方「数据包」可能包含为本次修改新增的数据集，"
            "如航迹表、时间序列等，请优先用它们实现意见中的诉求）；"
            "只能使用已给出的数据包，严禁编造数据；\n"
            "3. 上方「页面规划」中的区块仅为支撑参考；当修改意见与规划冲突时以修改意见为准，\n"
            "   若意见所需的数据当前数据包中确实没有，按「暂无相关数据」空态处理，不得造假；\n"
            "4. 仍然遵守全部运行时契约，直接输出完整单文件 HTML，不要解释。"},
    ]


# ──────────────────────────────────────────────────────────────────
# 4) 技能剧本注入（渐进披露的第二级：命中技能后才追加）
#
# 技能未命中时，两个 format 函数都返回空串，三个 build_*_messages 的输出
# 与改造前逐字节一致 —— 这是「不影响当前生成效果」的硬约束。
# ──────────────────────────────────────────────────────────────────

def _skill_of(skill_context: Dict[str, Any]):
    """取技能对象；未套用或缺对象时返回 None。"""
    if not isinstance(skill_context, dict) or not skill_context.get("applied"):
        return None
    return skill_context.get("skill")


def _skill_match_reason(skill_context: Dict[str, Any]) -> str:
    """技能套用原因的简短中文描述（匹配方式 + 匹配度）。"""
    labels = {"auto": "自动匹配", "manual": "手动指定", "inherited": "继承上一版页面"}
    label = labels.get(str(skill_context.get("matchedBy") or ""), "已套用")
    score = skill_context.get("score")
    if isinstance(score, (int, float)):
        return f"{label}，匹配度 {float(score):.3f}"
    return label


def format_skill_plan_guide(skill_context: Dict[str, Any]) -> str:
    """Planner 技能指南：取数剧本（已解析成真实数据集）+ 区块剧本 + 硬性约束。

    数据集由 ipage 按实体语义槽位确定性解析，模型只做「按剧本落位」，不猜数据集 ——
    这是技能换数据源后不失效的关键。
    """
    skill = _skill_of(skill_context)
    if skill is None:
        return ""
    sections = skill.body_sections or {}
    needs = skill_context.get("needs") or []

    lines = [
        f"【本次已套用技能：{skill.name}（{_skill_match_reason(skill_context)}）】",
        "请按下面的技能剧本组织页面规划。已给出数据集 ID 的需求必须使用该数据集，"
        "不得替换或编造数据集；未给出数据集 ID 的需求由你从下方目录中选择语义最接近的数据集。",
        "",
        "取数剧本：",
    ]
    if needs:
        for item in needs:
            if item.get("datasetId"):
                lines.append(
                    f"- 数据集ID={item.get('datasetId')}｜{item.get('datasetName')}"
                    f"｜mode={item.get('mode')}｜geo={item.get('geo')}"
                    f"｜要回答：{item.get('question')}")
            else:
                lines.append(
                    f"- 待选表（{item.get('reason') or '按目录选表'}）"
                    f"｜mode={item.get('mode')}｜geo={item.get('geo')}"
                    f"｜要回答：{item.get('question')}")
    else:
        lines.append("- （本次没有声明的数据需求，请按技能区块剧本自行补齐取数）")

    block_script = str(sections.get("区块剧本") or "").strip()
    if block_script:
        lines += ["", "区块剧本：", block_script]

    lines += ["", "硬性要求："]
    if skill.required_sections:
        lines.append(f"- sections 必须覆盖这些区块类型：{'、'.join(skill.required_sections)}")
    if skill.map_modes:
        lines.append(f"- 必须包含地图区块，且其 ref 指向声明了 geo（{'/'.join(skill.map_modes)}）的子问题")
    lines.append("- 其余规划要求（区块数量、结论区、地理形态与坐标字段匹配等）保持不变")
    return "\n".join(lines)


def format_skill_page_guide(skill_context: Dict[str, Any]) -> str:
    """PageWriter 技能指南：区块剧本 + 呈现偏好 + 叙事要点 + 交互 + 动态演示。"""
    skill = _skill_of(skill_context)
    if skill is None:
        return ""
    sections = skill.body_sections or {}
    lines = [f"【本次已套用技能：{skill.name}】",
             "在遵守上述运行时契约的前提下，按下面的技能剧本组织页面结构与呈现。", ""]
    for key in ("区块剧本", "呈现偏好", "叙事要点"):
        text = str(sections.get(key) or "").strip()
        if text:
            lines += [f"## {key}", text, ""]
    if skill.recommended_chart_types:
        lines += [f"推荐图表类型：{'、'.join(skill.recommended_chart_types)}"
                  "（数据实际不支持时按数据选型）", ""]
    if skill.interactions:
        lines += ["## 交互要求", "- " + "；".join(skill.interactions), ""]
    if skill.playback:
        lines += ["【动态演示】本技能要求航迹地图开启时间轴回放：给 SitMap 传 spec.playback，"
                  "由运行时提供播放条与「飞机随播放移动 + 航迹渐进显示」，禁止自行实现播放器。", ""]
    return "\n".join(lines).rstrip()
