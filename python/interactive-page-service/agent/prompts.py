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
2.1 需要"用时间轴拖动联动变化的图表"时，规划 mode=timeseries（按时间桶预聚合）：
   可指定 timeField（真实时间列，缺省由系统按注解/列名识别）、可选 groupBy（最多 3 列）与
   metric（count/sum/avg/max/min，缺省 count）；timeseries 的 geo 必须为 none，
   且规划中必须包含 timeline 区块（ref 指向该 timeseries 子问题），页面会以统一时间轴同步驱动
   地图与图表。数据集没有可识别时间列时不要规划 timeseries；
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
            "并声明 geo=tracks（页面用 SitMap timeline:true 让能力范围圈随飞机移动）；"
            "只有需要静止阵地/目标的固定范围圈时才声明 geo=circles（表须有半径字段）；\n"
            "2.2 需要图表随统一时间轴联动时，追加 mode=timeseries 子问题（时间桶聚合）"
            "并在 sections 中包含 timeline 区块（ref 指向该子问题）；\n"
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

    **时间轴联动（可选）**：data.timeline 存在、且数据来自 mode=timeseries 的时序数据集时，
    给 chart spec 增加 timeline 配置并显式传 rows（页面端只筛选/透视，不做业务聚合）：
      timeline: { mode:'trend'|'bucket', bucketField:'bucketKey', valueField:'数量', categoryField:'机型' }
      rows: data.datasets[i].rows
      - trend ：随时间轴累积到当前桶并高亮当前时刻（适合 line / bar 趋势）
      - bucket：只显示覆盖当前时刻的一个桶（适合分类对比 bar / pie）
      - categoryField 可省略（单系列曲线）
    没有时间列的数据集不要传 timeline —— 该图表在拖动时间轴时保持静态。

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
      // 页面时间轴联动（新契约）：data.timeline 存在时传 timeline:true，
      // 地图订阅 SitTimeline 的统一时钟，播放条由页面时间轴提供（不要同时传 playback）
      timeline: true
    }
    （兼容旧页面的 playback 配置仍可用，但新页面不要再使用；详见"三、SitTimeline"）
    多数据集上图：遍历 data.datasets，把各 ds.geoFeatures 的 units/tracks/circles 分别 concat 后传入；
    同一数据集 geoFeatures.units 不存在时回退使用 points。
    返回 mapApi：
      mapApi.on('featureClick', function(f){ /* f={kind:'unit'|'track'|'circle', name, faction, props} */ });
      mapApi.flyTo(lng, lat, zoom);
      mapApi.highlight(function(f){ return f.faction === '红方'; });   // 联动高亮
      mapApi.playback.play() / pause() / toggle() / seek(0~1) / reset();
      mapApi.playback.on(function(s){ /* s={index,total,ratio,time,playing} */ });
    坐标一律用 WGS84 经纬度（数据集里的原始坐标），运行时按底图自动转换。
    **图例即图层开关**：运行时按上图要素自动生成"图层 / 图例"面板，支持逐架飞机的
    飞机图标/航迹线/侦察圈/打击圈/侦察扫掠带/打击扫掠带，以及全局航迹线、扫掠区域、
    侦察/打击范围圈、单位分组与静态范围圈的独立开关（默认全部显示）；
    页面**不要自绘图例**，也不要重复添加控件。

    **地图视图自动锁定**：同一容器反复调用 SitMap.render（如时间轴播放轨迹）时，
    运行时会**自动保留用户的缩放/拖动视图**，不会因数据变化而重新 fitBounds。因此：
    - 时间轴播放时**不要**每次 render 都传 center，也**不要**在播放循环中调用 flyTo；
    - 仅在确实需要把地图定位到特定坐标（如点击某架飞机聚焦）时，才传 center 或调用 flyTo；
    - 首次渲染不传 center 会自动适配到全部数据范围（开启 playback 时已把半径计入）。

三、SitTimeline —— 页面级时间轴（页面唯一时钟；控件由宿主渲染，页面不画控件）
    data.timeline 存在时，页面必须在结论区之后放一个空占位容器并调用：
      var tl = SitTimeline.render('#tl', { axis: data.timeline.buckets });
    该容器只做占位：无标题、无高度、无卡片样式，运行时不再在其中绘制播放条。
    脚本顺序上**必须先调用 SitTimeline.render 建时钟，再渲染需要联动的图表和地图**；
    容器视觉上可以放在结论区之后，但不要因为视觉位置把它挪到最后才执行。
    播放/暂停、进度拖动、完整时间标签、重置由宿主浮层渲染
    （固定在窗口底部、不随页面滚动移动、常驻展开），通过消息驱动同一个时钟；
    回放为固定 1 秒/帧的逐帧显示，每帧对齐一条真实采样时刻，不做插值，不提供倍速。
    页面禁止自绘按钮、滑块、进度条，也不要额外创建第二个播放条。
    当前时刻变化时通过 SitBus 广播 'timeline:tick'（s={index,total,ratio,time,t,playing}）。
    组件联动：
    1. 地图：SitMap.render(el, { tracks, units, timeline: true }) 绑定页面时钟，按当前帧
       对齐最近真实航迹点、渐进显示已飞航段、画动态能力圈/扫掠走廊、按事件时刻显隐事件点；
    2. 图表：**按需**绑定，只给"按时间桶聚合且与地图共用同一时间刻度"的图表配置 timeline
       （见"一、SitChart"），trend 累积增长、bucket 切换当前桶；
    3. 没有时间列、或时间口径与地图对不上的图表不要传 timeline，保持静态；
    4. 不要再给 SitMap 传 spec.playback，也不要在页面里写 setInterval/滑块/自绘航迹——
       否则会出现"地图自己播、图表不动"的双时钟；需要自定义交互时只订阅 tl.on(fn)
       或 SitBus.on('timeline:tick', fn)。
    **兼容说明**：无 data.timeline 的历史页面仍可用 SitMap spec.playback（地图内自带播放条，
    含日内归一化）；新页面一律优先使用 SitTimeline。

四、SitBus —— 组件联动事件总线
    SitBus.on('filter', function(payload){ ... });      // payload.faction 为当前阵营（'' = 全部）
    SitBus.emit('filter', {faction:'蓝方'});            // 页面自定义筛选时 emit
    阵营筛选由宿主浮层统一驱动：运行时已自动过滤地图与图表，切换后还会广播
    'filter'（payload={faction}）与 'faction:change'；页面可选订阅它们联动 KPI/表格，
    但不要重复过滤地图/图表的数据。其它筛选器/Tab 变化时 emit，KPI 与图表订阅后重算重绘。

五、SitUtil / SitTable —— 工具
    SitUtil.esc(s)                 HTML 转义（拼 innerHTML 时必须用）
    SitUtil.fmtInt(n)              千分位整数
    SitUtil.fmtNum(n, digits)      固定小数位
    SitUtil.fmtPct(n, digits)      百分比（n 为 0-1 或 0-100 自动识别）
    SitUtil.groupBy(rows, key)     -> {类别: [行]}
    SitUtil.sum(rows, key) / avg(rows, key) / countBy(rows, key)
    SitUtil.unique(rows, key)      去重值列表
    SitTable.render(el, {columns:[{key,label}], rows, pageSize:rows.length})  明细表；
        页面下部的明细表要平铺展示，pageSize 传全部行数、不传 maxHeight，不要分页或内部滚动

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
2. 版式：页头 → KPI 行 → 主区（左图表 / 右地图）→ 明细表 → 结论，分「单屏区」与「平铺区」两部分：
   - 单屏区（页头 + KPI + 主区）高度固定为宿主注入的 var(--ipage-vh,720px)：
     纵向 flex，页头/KPI 为 auto，主区 flex:1;min-height:0；
     **不要用 100vh 计算高度**（iframe 自动撑高时 100vh 等于内容高，会形成反馈循环）；
   - 明细表（如战损明细记录）与结论放在单屏区之外，向下自然平铺，页面总高可以超过一屏：
     不要给它们设固定高度/max-height/overflow 滚动条，也不要分页（SitTable 的 pageSize 传全部行数）；
   - 时间轴浮层常驻底部，--ipage-vh 已扣除其高度，页面无需再额外预留底部空间；
   主区左右分栏，左宽用 --ipage-left（脚本按图表数设置，不要直接写内联 grid-template-columns）：
   leftPct = clamp(32, 28 + 4 * 图表数, 58)；
   左栏图表排列按数量决定（脚本设置网格列数与行轨道）：
   - 1~3 张：单列纵向均分；
   - 4 张：2 列 × 2 行；
   - 5 张：上方 2×2、下方通栏一张（优先放可拉宽的折线图，卡片 grid-column:1/-1）；
   - 6 张及以上：2 列，行数按 ceil(图表数/2)；
   单个图表卡片限制尺寸：max-width:520px、max-height:420px（通栏折线图例外，占满左栏但
   max-width:900px），高度由行轨道均分且不要设 min-height（避免小屏挤压溢出），
   宽高比不固定但受这两个上限约束；图表容器 height:100%；
   右栏地图容器 height:100%，不要再写死 420-520px；
   无地理数据时主区退化为单列全宽图表，不得虚构地图；窗口窄于 900px 时上下堆叠、
   取消固定高度并恢复自然滚动；
3. 图表选型匹配数据：比较/排名用 bar，时间趋势用 line，占比（≤8 类）用 pie，
   多维能力对比用 radar，两数值维度分布用 scatter；每个图表有中文标题与一句话结论（可放卡片下方）；
   图表标题一律用卡片内的 HTML 标题（.ip-title/h3），**调用 SitChart 时不要再传 title**，
   否则画布内会重复画一遍标题并与图例、坐标轴文字互相压字；
4. 可交互：阵营筛选由运行时宿主浮层统一提供（同时控制地图与图表），**页面不要再自绘阵营按钮**；
   地图图例/图层开关（逐架飞机、航迹线、范围圈、扫掠区域）同样由运行时地图控件生成，
   页面不要自绘图例；其它维度（类别/状态等）可提供筛选按钮并通过 SitBus 联动
   KPI、图表、地图（地图用 mapApi.highlight）；**data.timeline 存在时必须有 timeline 区块**，
   但该区块只是结论区之后的空占位容器，调用 SitTimeline.render 建页面级时间轴（控件由宿主浮层渲染），
   地图传 timeline:true；图表**按需绑定**：只有数据本身按时间桶聚合、且与地图时间刻度一致的图表
   才传 timeline 配置，其余图表保持静态，不要为了联动强行绑定或改造数据；
   不要自己写播放器、不要自己画航迹折线；至少让页面上的关键控件真正生效，禁止摆设按钮；
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


def _has_geo_features(geo: Dict[str, Any]) -> bool:
    """判断 geoFeatures 是否包含可上车的地图要素（空数组视为无地图数据）。"""
    if not isinstance(geo, dict):
        return False
    return any(
        isinstance(geo.get(key), list) and bool(geo.get(key))
        for key in ("tracks", "points", "units", "circles")
    )


def _bundle_view(bundle: Dict[str, Any], sample_rows: int) -> Dict[str, Any]:
    """供 LLM 阅读的数据包视图：明细数据只给样例行 + 完整字段与总行数。"""
    view = {
        "question": bundle.get("question", ""),
        "generatedAt": bundle.get("generatedAt", ""),
        "datasets": [],
    }
    # 评估产物模式的综合结论：仅非空时附加，普通页面数据包视图保持不变
    conclusion = str(bundle.get("conclusion") or "").strip()
    if conclusion:
        view["conclusion"] = conclusion
    timeline = bundle.get("timeline") or {}
    if timeline:
        buckets = timeline.get("buckets") or []
        view["timeline"] = {
            "granularity": timeline.get("granularity"),
            "bucketSeconds": timeline.get("bucketSeconds"),
            "startTime": timeline.get("startTime"),
            "endTime": timeline.get("endTime"),
            "totalBuckets": len(buckets),
            "firstBuckets": buckets[:3],
            "lastBuckets": buckets[-2:],
            "note": "运行时 data.timeline.buckets 为完整刻度；页面用 SitTimeline.render 建轴，"
                    "地图传 timeline:true，时序图表传 timeline 配置",
        }
    for ds in bundle.get("datasets", []):
        rows = ds.get("rows", []) or []
        geo_features = ds.get("geoFeatures")
        entry = {
            "id": ds.get("id"),
            "name": ds.get("name"),
            "purpose": ds.get("purpose"),
            "mode": ds.get("mode"),
            "columns": ds.get("columns"),
            "totalRows": ds.get("totalRows", len(rows)),
            "truncated": ds.get("truncated", False),
            "geo": ds.get("geo", {"kind": "none"}),
            # 明确告知模型该数据集是否真的有可上车的地图要素（空数组=false）
            "geoAvailable": _has_geo_features(geo_features),
            "geoFeatures": _geo_features_view(geo_features),
            "summary": ds.get("summary", ""),
            "rowsSample": rows[:sample_rows],
            "sampleNote": (
                f"运行时数据包将包含全部 {ds.get('totalRows', len(rows))} 行（字段与样例完全一致），"
                "请按完整数据编写代码，下方仅展示前若干行样例。"
                if ds.get("mode") == "detail" and len(rows) > sample_rows else ""
            ),
        }
        if ds.get("mode") == "timeseries":
            entry.update({
                "bucketSeconds": ds.get("bucketSeconds"),
                "valueField": ds.get("valueField"),
                "timeField": ds.get("timeField"),
                "groupBy": ds.get("groupBy") or [],
                "timelineNote": "该数据集已按时间桶预聚合；图表用 timeline 配置 + rows 绑定，不要自行再聚合",
            })
        view["datasets"].append(entry)
    # 顶层地图可用性：只有存在非空 geoFeatures 的数据集时才为 true
    view["mapAvailable"] = any(bool(entry.get("geoAvailable")) for entry in view["datasets"])
    return view


EVALUATION_PAGE_GUIDE = """
【评估产物模式】
本页数据来自已完成的评估分析结果，不是在本次生成中重新取数：
- 页面中的数值只能来自数据包，禁止自行推算、补全或修改数字；
- 数据包可能包含 conclusion 字段（评估结论），结论区必须直接用 data.conclusion 渲染，
  可以归纳表达，但不得新增结论；
- 地图渲染硬约束：仅当 data.mapAvailable === true 且「页面规划」sections 中存在 kind="map"
  的区块时，才创建地图容器并调用 SitMap.render；否则禁止输出任何地图 DIV、地图标题或
  SitMap 调用，不要生成空白地图；
- 不得输出「数据待补充」「TODO」等占位内容。
"""


def build_page_messages(query: str, plan: Dict[str, Any], bundle: Dict[str, Any],
                        sample_rows: int,
                        skill_context: Dict[str, Any] = None) -> list:
    """页面首次生成消息。

    skill_context 为空（未命中技能）时，消息与改造前完全一致；
    plan.origin.type='evaluation' 时追加「评估产物模式」写作约束。
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
    origin = (plan.get("origin") or {}) if isinstance(plan, dict) else {}
    evaluation_guide = (
        "\n" + EVALUATION_PAGE_GUIDE
        if str(origin.get("type") or "") == "evaluation" else ""
    )
    return [
        {"role": "system",
         "content": PAGE_SYSTEM_HEADER + (("\n" + guide) if guide else "") + evaluation_guide},
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
        lines += ["【动态演示】本技能要求航迹地图支持逐帧回放：数据包有统一时间轴时，"
                  "先 SitTimeline.render 建时钟，再给 SitMap 传 timeline:true（禁止同时传 playback）；"
                  "仅无统一时间轴的历史兼容场景才给 SitMap 传 spec.playback。"
                  "两种方式都由运行时负责「飞机随帧对齐真实位置 + 航迹渐进显示」，禁止自行实现播放器。", ""]
    return "\n".join(lines).rstrip()
