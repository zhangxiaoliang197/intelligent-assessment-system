"""Planner —— 规划智能体（function-calling 产出页面大纲与取数计划）。

输出 emit_page_plan：
- intent: data_page / general（非数据问题直答，不产页面）
- subQuestions：并行取数单元（aggregate 聚合 / detail 明细 + 地理形态）
- sections：页面区块大纲（kpi/chart/map/text/table/filters/timeline）

LLM 失败最多 3 次；最终失败时用确定性最小计划兜底。
"""
import json
import logging
from typing import Any, Dict, List, Optional

import config
from llm_client import call_llm_with_tools
from agent import prompts

logger = logging.getLogger("ipage-service")

EMIT_PAGE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_page_plan",
        "description": "提交交互页面规划：意图识别、取数子问题与页面区块大纲。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["intent", "subQuestions", "sections"],
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["data_page", "general"],
                    "description": "data_page=需要查数据并生成页面；general=闲聊/通用问答/概念解释",
                },
                "directAnswer": {
                    "type": "string",
                    "description": "intent=general 时的中文直接回答；data_page 时省略",
                },
                "title": {
                    "type": "string",
                    "description": "页面标题（不超过 25 字），data_page 时必填",
                },
                "subQuestions": {
                    "type": "array",
                    "maxItems": 6,
                    "description": "取数子问题，data_page 时 1-5 个",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "datasetId", "question", "mode"],
                        "properties": {
                            "id": {"type": "string", "description": "子问题 ID，如 q1/q2"},
                            "datasetId": {"type": "string", "description": "必须来自数据集目录"},
                            "question": {"type": "string", "description": "本子问题要回答的事实，聚焦可量化内容"},
                            "mode": {
                                "type": "string", "enum": ["aggregate", "detail"],
                                "description": "aggregate=聚合统计供图表；detail=逐行明细供地图/表格",
                            },
                            "geo": {
                                "type": "string",
                                "enum": ["none", "points", "tracks", "circles"],
                                "description": "地理形态：无坐标 none；单位/事件位置 points（基地/阵地/威胁/目标/事件，运行时自动符号化）；逐点航迹 tracks（含实体编号/序号/时间）；装备能力范围圈 circles",
                            },
                            "filters": {
                                "type": "object",
                                "description": "可选过滤条件，key=真实字段名；区间用 {gte,lte}",
                            },
                        },
                    },
                },
                "sections": {
                    "type": "array",
                    "maxItems": 10,
                    "description": "页面区块（按展示顺序），data_page 时 3-8 个",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "kind", "title"],
                        "properties": {
                            "id": {"type": "string", "description": "区块 ID，如 s1/s2"},
                            "kind": {
                                "type": "string",
                                "enum": ["kpi", "chart", "map", "text", "table", "filters", "timeline"],
                            },
                            "title": {"type": "string", "description": "区块标题（text 区可写『分析结论』）"},
                            "purpose": {"type": "string", "description": "该区想说明什么/展示什么"},
                            "ref": {"type": "string", "description": "关联的 subQuestion id（chart/map/table/kpi 建议填写）"},
                        },
                    },
                },
                "interactions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "期望的交互，如：阵营筛选联动、航迹选择、时间轴回放",
                },
            },
        },
    },
}


def _available_dataset_ids(meta: Dict[str, Any]) -> set:
    """从 /export/for-llm 元数据收集可用数据集 ID。"""
    if not isinstance(meta, dict) or not meta.get("success"):
        return set()
    schemas = (meta.get("data", {}) or {}).get("schemas", []) or []
    ids = set()
    for schema in schemas:
        ds_id = str((schema or {}).get("datasetId") or (schema or {}).get("id") or "").strip()
        if ds_id:
            ids.add(ds_id)
    return ids


def _geo_capable_ids(meta: Dict[str, Any]) -> set:
    """根据字段名启发式判断具备成对经纬度的数据集。"""
    if not isinstance(meta, dict) or not meta.get("success"):
        return set()
    schemas = (meta.get("data", {}) or {}).get("schemas", []) or []
    capable = set()
    for schema in schemas:
        fields = (schema or {}).get("fields") or (schema or {}).get("columns") or []
        lngs, lats = [], []
        for f in fields:
            if not isinstance(f, dict):
                continue
            col = str(f.get("name") or f.get("column") or f.get("fieldName") or "").lower()
            if col.endswith("_lng") or col in ("lng", "lon", "longitude"):
                lngs.append(col)
            if col.endswith("_lat") or col in ("lat", "latitude"):
                lats.append(col)
        ds_id = str(schema.get("datasetId") or schema.get("id") or "").strip()
        if ds_id and lngs and lats:
            capable.add(ds_id)
    return capable


def _validate(plan: Dict[str, Any], available: set, geo_capable: set) -> Optional[str]:
    """校验规划，返回错误原因；None 表示通过。"""
    if not isinstance(plan, dict):
        return "工具参数不是对象"
    intent = str(plan.get("intent") or "").strip()
    if intent not in ("data_page", "general"):
        return "intent 必须是 data_page 或 general"
    if intent == "general":
        if not str(plan.get("directAnswer") or "").strip():
            return "intent=general 时 directAnswer 不能为空"
        return None

    sub_questions = plan.get("subQuestions")
    if not isinstance(sub_questions, list) or not sub_questions:
        return "data_page 至少需要 1 个 subQuestion"
    if len(sub_questions) > 6:
        return "subQuestions 不能超过 6 个"

    q_ids = set()
    geo_q_ids = set()
    for idx, sq in enumerate(sub_questions):
        if not isinstance(sq, dict):
            return f"subQuestions[{idx}] 不是对象"
        qid = str(sq.get("id") or "").strip()
        if not qid:
            return f"subQuestions[{idx}].id 为空"
        if qid in q_ids:
            return f"subQuestion id 重复: {qid}"
        q_ids.add(qid)
        ds_id = str(sq.get("datasetId") or "").strip()
        if not ds_id:
            return f"subQuestions[{idx}].datasetId 为空"
        if available and ds_id not in available:
            return f"subQuestions[{idx}].datasetId={ds_id} 不在可用数据集目录中"
        mode = str(sq.get("mode") or "aggregate").strip()
        if mode not in ("aggregate", "detail"):
            return f"subQuestions[{idx}].mode 必须是 aggregate 或 detail"
        geo = str(sq.get("geo") or "none").strip()
        if geo not in ("none", "points", "tracks", "circles"):
            return f"subQuestions[{idx}].geo 非法"
        if geo != "none":
            if available and ds_id not in geo_capable:
                return f"subQuestions[{idx}].datasetId={ds_id} 无成对经纬度字段，不能规划 {geo}"
            geo_q_ids.add(qid)

    sections = plan.get("sections")
    if not isinstance(sections, list) or len(sections) < 3:
        return "data_page 页面区块至少 3 个（建议 kpi + 2 个以上图表 + 结论）"
    kinds = [str(s.get("kind") if isinstance(s, dict) else "") for s in sections]
    if "chart" not in kinds and "map" not in kinds:
        return "页面至少要包含一个 chart 或 map 可视化区块"
    if "text" not in kinds:
        return "页面必须包含一个 text 分析结论区块"
    sec_ids = set()
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            return f"sections[{idx}] 不是对象"
        sid = str(sec.get("id") or "").strip()
        if not sid or sid in sec_ids:
            return f"sections[{idx}].id 为空或重复"
        sec_ids.add(sid)
        kind = str(sec.get("kind") or "")
        if kind not in ("kpi", "chart", "map", "text", "table", "filters", "timeline"):
            return f"sections[{idx}].kind 非法: {kind}"
        ref = str(sec.get("ref") or "").strip()
        if ref and ref not in q_ids:
            return f"sections[{idx}].ref={ref} 未命中任何 subQuestion"
        if kind == "map" and ref and ref not in geo_q_ids:
            return f"sections[{idx}] 地图区块引用的 {ref} 未声明 geo 形态"
    return None


def _fallback_plan(meta: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Planner 彻底失败时的确定性最小计划（取第一个可用数据集）。"""
    schemas = (meta.get("data", {}) or {}).get("schemas", []) if isinstance(meta, dict) else []
    ds_id, ds_name = "", ""
    geo = "none"
    if schemas:
        first = schemas[0] or {}
        ds_id = str(first.get("datasetId") or first.get("id") or "")
        ds_name = str(first.get("name") or first.get("tableName") or ds_id)
        geo_capable = _geo_capable_ids(meta)
        geo = "points" if ds_id in geo_capable else "none"
    sections = [
        {"id": "s1", "kind": "kpi", "title": "核心指标", "ref": "q1"},
        {"id": "s2", "kind": "chart", "title": f"{ds_name or '数据'}统计", "ref": "q1"},
        {"id": "s3", "kind": "text", "title": "分析结论", "ref": "q1"},
    ]
    if geo != "none":
        sections.insert(2, {"id": "s-map", "kind": "map", "title": "空间分布", "ref": "q1"})
    return {
        "intent": "data_page",
        "title": query[:25] or "态势交互页面",
        "subQuestions": [{
            "id": "q1", "datasetId": ds_id, "question": query,
            "mode": "detail" if geo != "none" else "aggregate", "geo": geo,
        }],
        "sections": sections,
        "interactions": [],
        "_fallback": True,
    }


class Planner:
    """页面规划智能体。"""

    def __init__(self, meta: Dict[str, Any]):
        self.meta = meta
        self.available = _available_dataset_ids(meta)
        self.geo_capable = _geo_capable_ids(meta)

    def plan(self, query: str, parent_query: str = "",
             parent_plan: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用 LLM 产出页面计划；失败 3 次后确定性兜底。

        Args:
            query: 用户问题（修订场景即修改意见）
            parent_query: 上文问题（首次生成时的承接上下文）
            parent_plan: 修订场景的父页面规划；传入即走「延续式」规划 ——
                已有子问题必须原样沿用，只为新需求追加子问题

        Returns:
            规划字典；intent=general 时含 directAnswer。
        """
        # 无任何已注册可用数据集：直接给出中文说明，不消耗 LLM 调用
        if not self.available:
            return {
                "intent": "general",
                "directAnswer": "当前没有已注册并可用于分析的数据集（可能数据集尚未配置字段注解），"
                                "无法生成交互页面。请先在基础管理系统中注册数据集后再试。",
            }
        catalog = prompts.format_meta_catalog(self.meta)
        if isinstance(parent_plan, dict) and (parent_plan.get("subQuestions")):
            messages = prompts.build_replan_messages(query, catalog, parent_plan)
        else:
            messages = prompts.build_plan_messages(query, catalog, parent_query)
        last_error = ""
        for attempt in range(1, 4):
            try:
                result = call_llm_with_tools(
                    messages=messages,
                    tools=[EMIT_PAGE_PLAN_TOOL],
                    tool_choice={"type": "function", "function": {"name": "emit_page_plan"}},
                    temperature=0.2,
                    max_tokens=min(config.LLM_MAX_TOKENS, 6000),
                    thinking_type=config.IPAGE_STRUCT_THINKING,
                )
            except Exception as exc:
                last_error = str(exc)[:200]
                logger.warning("Planner 第 %s 次调用异常: %s", attempt, last_error)
                messages = messages + [{
                    "role": "user",
                    "content": f"上一次调用失败：{last_error}。请重新调用 emit_page_plan 工具。",
                }]
                continue

            tc = next((t for t in result.get("tool_calls", [])
                       if t.get("name") == "emit_page_plan"), None)
            if tc is None:
                last_error = "未调用 emit_page_plan"
                messages = messages + [{
                    "role": "user", "content": "必须调用 emit_page_plan 工具提交规划。",
                }]
                continue
            args = tc.get("arguments")
            if not isinstance(args, dict):
                last_error = "arguments 为空或 JSON 解析失败"
                messages = messages + [
                    {"role": "assistant", "content": result.get("content") or "",
                     "tool_calls": [{
                         "id": tc.get("id", ""), "type": "function",
                         "function": {"name": "emit_page_plan",
                                      "arguments": json.dumps(args, ensure_ascii=False)
                                      if isinstance(args, dict) else "{}"},
                     }]},
                    {"role": "tool", "tool_call_id": tc.get("id", ""),
                     "content": "arguments 无效，请填写完整 JSON 重新调用。"},
                ]
                continue
            err = _validate(args, self.available, self.geo_capable)
            if err:
                last_error = err
                logger.warning("Planner 第 %s 次校验失败: %s", attempt, err)
                messages = messages + [{
                    "role": "user",
                    "content": f"规划校验失败：{err}。请修正后重新调用 emit_page_plan。",
                }]
                continue

            if not args.get("title"):
                args["title"] = query[:25]
            args.pop("_fallback", None)
            logger.info("Planner 成功（第 %s 次）: subQuestions=%s sections=%s",
                        attempt, len(args.get("subQuestions", [])), len(args.get("sections", [])))
            return args

        logger.warning("Planner 3 次均失败，启用确定性兜底: %s", last_error)
        if not self.available:
            return {"intent": "general",
                    "directAnswer": "当前没有已注册可用于分析的数据集，无法生成交互页面。请先在数据管理中注册数据集。",
                    "_planner_error": last_error}
        fallback = _fallback_plan(self.meta, query)
        fallback["_planner_error"] = last_error
        return fallback
