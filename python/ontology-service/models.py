"""本体的数据模型（两层分离：实体类型层 / 实体实例层）。

v3 重构：删除 ConceptType 实体类型层，将其层级 + property_schema 能力合并进 EntityType。
EntityType 形成树状层级（parent_entity_type_id），Entity 直接 instance_of → EntityType.id。
新增 EntityTypeRelation 存储类型间关系（step1 提取），Relation 仅存实例间关系（step2 提取）。

从 main.py 抽出，供 repository 层与 main.py 共享。
所有模型为纯数据载体，不含业务逻辑。
"""
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid as _uuid


# 数据 schema 版本（与 migration.SCHEMA_VERSION 保持一致）
# v1=旧（Dict 属性）, v2=三层（ConceptType 实体类型层）, v3=两层（EntityType 带层级，删除 ConceptType）
SCHEMA_VERSION = 3


class RelationType(BaseModel):
    """本体模型关系类型。"""
    name: str
    description: str = ""


class PropertySchema(BaseModel):
    """属性骨架：定义某类实体类型应具备的属性模板。

    EntityType 携带 property_schema 列表，实例化为实体时 LLM 按此骨架填充属性。
    属性继承：子类型的 property_schema 自动并入父类型的属性（并集，按 name 去重）。
    """
    name: str                            # 属性名，如"资产负债率"
    category: str = "descriptive"        # descriptive（描述型）| metric（指标型）
    data_type: str = "string"            # string | number | date | enum
    unit: str = ""                       # 单位，如"%""万元"
    required: bool = False
    description: str = ""


class PropertyHistoryEntry(BaseModel):
    """属性历史值条目（仅指标型属性会有历史值）。"""
    value: Any = None
    recorded_at: Optional[datetime] = None   # 采集时间
    source_snippet: str = ""                 # 该历史值的来源原文
    note: str = ""


class PropertyVerification(BaseModel):
    """属性验证结果（step3 LLM 自检后写入，Phase 1 预留字段）。"""
    status: str = "verified"             # verified | suspect | unverified
    reason: str = ""                     # 存疑原因


class Property(BaseModel):
    """结构化属性：依附实体或关系，区分描述型/指标型。

    指标型属性支持历史版本（history）和数据字段绑定（bindings）。
    """
    id: str                              # prop_xxxx
    entity_id: str = ""                  # 所属实体/关系ID（关系属性时存关系ID）
    name: str                            # 属性名，如"资产负债率"
    value: Any = None                    # 当前值
    category: str = "descriptive"        # descriptive（描述型）| metric（指标型）
    data_type: str = "string"            # string | number | date | enum
    unit: str = ""                       # 单位
    source_snippet: str = ""             # 属性值来源原文（可溯源）
    # 指标型属性的数据字段绑定（复用 ass_field_annotation）
    bindings: Dict[str, str] = Field(default_factory=dict)
    # 指标历史版本：指标型属性更新时旧值自动追加
    history: List[PropertyHistoryEntry] = Field(default_factory=list)
    # 验证标记（step3 LLM 自检后写入）
    verification: Optional[PropertyVerification] = None
    create_time: datetime
    update_time: datetime


class EntityType(BaseModel):
    """实体类型（类型层，合并原 EntityType 本体模型 + ConceptType 实体类型层）。

    v3 重构：EntityType 自带层级（parent_entity_type_id）+ property_schema（属性骨架），
    形成树状层级：一级实体类型 → 二级实体类型 → ... → 最低层级实体类型。
    最低层级实体类型由实体实例组成（Entity.instance_of 指向某层级的 EntityType）。

    属性继承：子类型自动继承父类型的 property_schema（并集，按 name 去重），
    实例化时按并集填充属性。继承在运行时由 get_inherited_property_schema 计算，
    不在存储层冗余。

    层级深度不限，但通常 2-3 层（避免过度细化）。
    """

    @model_validator(mode='before')
    @classmethod
    def _fill_v2_defaults(cls, data: Any) -> Any:
        """v2→v3 兼容：自动填充缺失的必填字段（id/create_time/update_time）。

        v2 本体模型 entity_types 仅含 {name, color}，v3 EntityType 合并了 ConceptType
        后要求 id/create_time/update_time。此 validator 确保旧数据可被加载，
        避免每个加载点（索引/数据文件/导入）都需预处理。
        """
        if isinstance(data, dict):
            now = datetime.now()
            if not data.get('id'):
                data['id'] = f"et_{_uuid.uuid4().hex[:8]}"
            if not data.get('create_time'):
                data['create_time'] = now
            if not data.get('update_time'):
                data['update_time'] = now
        return data

    id: str                              # et_xxxx
    ontology_id: str = ""                # 所属本体ID
    name: str                            # 类型名，如"企业""上市企业""财务指标"
    description: str = ""                # 类型释义
    color: Optional[str] = None          # 前端展示颜色
    property_schema: List[PropertySchema] = Field(default_factory=list)
    source_snippet: str = ""             # 类型来源原文（防幻觉）
    # 父实体类型 ID（层级关系）：空表示顶层类型
    # 例：企业(parent=None) → 上市企业(parent=企业) → A公司(instance_of=上市企业)
    parent_entity_type_id: Optional[str] = None
    # 临时字段（仅 LLM 输出用，不持久化）：父类型名，build_confirm_step1 时解析为 parent_entity_type_id
    parent_entity_type_name: Optional[str] = None
    create_time: datetime
    update_time: datetime

    # ── v3 兼容层：旧代码引用 c.entity_type / c.parent_concept_id 等仍可工作 ──
    @property
    def entity_type(self) -> str:
        """兼容旧 ConceptType.entity_type：v3 中 EntityType 自身就是类型，返回自身 name。"""
        return self.name

    @property
    def parent_concept_id(self) -> Optional[str]:
        """兼容旧 ConceptType.parent_concept_id → EntityType.parent_entity_type_id。"""
        return self.parent_entity_type_id

    @property
    def parent_concept_name(self) -> Optional[str]:
        """兼容旧 ConceptType.parent_concept_name → EntityType.parent_entity_type_name。"""
        return self.parent_entity_type_name


class EntityTypeRelation(BaseModel):
    """实体类型间的关系（类型层关系，step1 提取）。

    描述实体类型之间的语义关联（如「企业」关联「财务指标」「企业」包含「子公司」），
    为图谱的类型层展示和实例层关系建模提供参考。

    与 Relation（实例间关系）的区别：
    - EntityTypeRelation 是 schema 层的抽象关系，描述类型间可能的关联模式
    - Relation 是数据层的具体关系，描述两个实体实例之间的实际关联
    """
    id: str                              # etr_xxxx
    ontology_id: str = ""
    source_entity_type_id: str           # 源实体类型 ID
    target_entity_type_id: str           # 目标实体类型 ID
    relation_type: str                   # 关系类型名（复用 OntologyModel.relation_types）
    description: str = ""
    source_snippet: str = ""             # 关系来源原文（防幻觉）
    weight: float = 1.0
    create_time: datetime
    update_time: datetime


class Entity(BaseModel):
    """实体（实例层）：具体的人/物/事。

    instance_of 指向 EntityType.id（v3 重构：不再指向 ConceptType）。
    实体可挂在任意层级的 EntityType 上（不限于叶子层级）。
    属性按所属 EntityType 的并集 property_schema（含继承）填充。
    """
    id: str
    ontology_id: str
    name: str
    instance_of: str = ""                # 实体类型ID（EntityType.id），替代原 type 字段
    # 兼容旧数据：迁移后的实体保留 type 字段为空串，新实体不用
    type: str = ""
    # 已弃用：原"选主要实体"步骤已移除，改为实体类型层级
    # 保留仅为向后兼容旧数据，新实体恒为 False
    is_primary: bool = False
    properties: List[Property] = Field(default_factory=list)
    # 数据字段绑定（实体级，保留向后兼容；指标型属性也可在 property.bindings 单独绑定）
    bindings: Dict[str, str] = Field(default_factory=dict)
    source_snippet: str = ""             # 实体来源原文
    create_time: datetime
    update_time: datetime


class Relation(BaseModel):
    """实体实例间的关系（实例层关系，step2 提取）。

    v3 重构：原 step3 关系建模合并到 step2，与实体提取同批完成。
    """
    id: str
    ontology_id: str
    source_id: str                       # 源实体ID（Entity.id）
    target_id: str                       # 目标实体ID（Entity.id）
    relation_type: str
    properties: List[Property] = Field(default_factory=list)
    # 数据绑定：关系绑定到具体指标（ass_indicator）
    bindings: Dict[str, str] = Field(default_factory=dict)
    weight: float = 1.0
    source_snippet: str = ""             # 关系来源原文
    create_time: datetime
    # 关系无 update_time（向后兼容）；必须为 Optional，否则 pydantic v2 校验
    # "update_time": null 会失败，导致 load_db 时关系整体被跳过
    update_time: Optional[datetime] = None


class OntologyModel(BaseModel):
    """本体（一个独立的本体空间，隔离实体类型/实体/关系）。"""
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    # v3：entity_types 为完整的 EntityType 列表（带层级 + property_schema）
    entity_types: List[EntityType] = Field(default_factory=list)
    relation_types: List[RelationType] = Field(default_factory=list)
    create_time: datetime
    update_time: datetime
    status: str = "活跃"
    # 数据 schema 版本：1=旧（Dict 属性）, 2=三层（ConceptType）, 3=两层（EntityType 带层级）
    schema_version: int = SCHEMA_VERSION


class TemplateEntityTypeSchema(BaseModel):
    """本体模型内的实体类型 schema（剥离运行时字段，仅保留类型层定义）。

    与 EntityType 的区别：不含 id/ontology_id/source_snippet/create_time/update_time，
    避免实例溯源信息污染本体模型。保留 color 便于应用时新类型继承颜色保持视觉一致。

    支持层级：parent_entity_type_name 指向父类型名（本体模型内按名引用，实例化时解析为 ID）。
    """
    name: str
    description: str = ""
    color: Optional[str] = None
    property_schema: List[PropertySchema] = Field(default_factory=list)
    # 父类型名（本体模型内按名引用，实例化时解析为 parent_entity_type_id）
    parent_entity_type_name: Optional[str] = None


class TemplateEntityTypeRelation(BaseModel):
    """本体模型内的实体类型间关系 schema（剥离运行时字段）。"""
    source_entity_type_name: str
    target_entity_type_name: str
    relation_type: str
    description: str = ""


class OntologyTemplateModel(BaseModel):
    """本体模型：从已有本体抽取的 schema 层，可作为新本体构建的参考。

    用途：
    1. 文档构建时载入本体模型：hard_constraint 强制按本体模型提取，soft_constraint 作软约束
    2. 手动构建向导启动时一键预填实体类型树 + 属性骨架 + 关系类型
    3. 用户选择本体模型时可跳过 step1 直接用本体模型的 EntityType 层级
    """
    id: str                                    # tpl_xxxxxxxx
    name: str
    description: str = ""
    version: str = "1.0.0"
    entity_types: List[TemplateEntityTypeSchema] = Field(default_factory=list)
    relation_types: List[RelationType] = Field(default_factory=list)
    entity_type_relations: List[TemplateEntityTypeRelation] = Field(default_factory=list)
    source_ontology_id: Optional[str] = None   # 溯源：从哪个本体抽取
    create_time: datetime
    update_time: datetime
    is_builtin: bool = False


# 向后兼容别名：旧代码仍引用 TemplateModel，重定向到 OntologyTemplateModel
TemplateModel = OntologyTemplateModel


class BuildJob(BaseModel):
    """本体分步构建任务（四阶段状态机，v3）。

    支持断点续作：每步结果持久化到 data/build_jobs/job_{id}.json。
    四阶段流程（已更名为文档构建四阶段）：
      upload（落盘源文件，不解析）→ step0 文档解析（解析文档 + 推荐本体模型 + 配置）
      → step1 类型提取（层级+属性+类型间关系）→ step2 实体提取（属性赋值+实例间关系）
      → step3 分析验证

    v3 变更：
    - 删除 step0 本体模型推荐（EntityType 层级由 step1 提取）
    - step1 合并原 step1 实体类型提取：提取 EntityType 层级 + property_schema + EntityTypeRelation
    - step2 合并原 step3 关系建模：实体提取 + 属性赋值 + 实例间 Relation
    - 原 step4 验证降为 step3
    - 文档解析下放为阶段 0 后台任务，upload 只落盘源文件并快速返回

    返工功能：每步可通过 rework 接口重新调用 LLM 重建（用户输入新提示词）。
    """
    id: str                                    # job_xxxxxxxx
    name: str                                  # 本体名称
    description: str = ""
    step: int = 0                              # 0=文档解析,1=类型提取,2=实体提取,3=分析验证,4=已完成
    status: str = "draft"                      # draft | completed | abandoned | legacy
    # 任务类型：document=文档构建 | manual=手动构建（无文档源，作为进行中任务入口）
    build_type: str = "document"               # document | manual

    # 文档源（持久化，支持断点续作）
    source_filename: str = ""
    source_text: str = ""                      # 解析后的纯文本
    char_count: int = 0                        # 文档字符数（前端展示用）

    # 预估分批数（step0 解析后预计算，用于前端展示"将分 N 批并行处理"）
    # step1/step2 实际运行时以 step1_batches_total / step2_batches_total 为准
    estimated_step1_batches: int = 0
    estimated_step2_batches: int = 0

    # Step 0 结果：配置（粒度 + 阶段提示词 + 本体模型）
    granularity: str = "medium"                # coarse | medium | fine（三档粒度预设）
    stage_hints: Dict[int, str] = {}           # {1: "重点关注财务指标", 2: "...", 3: "..."}
    # 参考本体模型：upload 时一次性快照，后续 step1-3 都从此读取
    ontology_model_id: Optional[str] = None                    # 关联 OntologyTemplateModel.id
    ontology_model_snapshot: Optional[Dict[str, Any]] = None   # upload 时一次性快照（OntologyTemplateModel.dict()）
    # 本体模型使用模式：hard_constraint=强制按本体模型提取（载入本体模型）；soft_constraint=本体模型作软约束；skip_step1=直接用本体模型跳过 step1
    ontology_model_mode: str = "soft_constraint"      # hard_constraint | soft_constraint | skip_step1

    # Step 1 结果：实体类型清单（含层级 + property_schema）+ 类型间关系
    step1_entity_types: List[Dict[str, Any]] = []
    step1_entity_type_relations: List[Dict[str, Any]] = []
    step1_confirmed: bool = False

    # Step 2 结果：实体+属性（实例层）+ 实例间关系
    step2_entities: List[Dict[str, Any]] = []
    step2_relations: List[Dict[str, Any]] = []   # v3：实例间关系合并到 step2
    step2_confirmed: bool = False

    # Step 3 结果：验证 + 报告
    step3_verification: Optional[Dict[str, Any]] = None  # {verified_count, suspect_count, suspects: [...]}
    step3_report: Optional[str] = None                    # LLM 生成的 markdown 简报
    step3_confirmed: bool = False

    # Step 1 分批状态（长文档分批提取实体类型，支持断点续作）
    step1_batches_total: int = 0
    step1_batches_done: int = 0
    step1_batch_results: List[List[Dict[str, Any]]] = []
    # v3 新增：每批次的实体类型间关系（与 step1_batch_results 同长度，同索引对齐）
    step1_batch_relations_results: List[List[Dict[str, Any]]] = []
    # v3 新增：跨批类型间关系补充（多批合并后由 LLM 补齐跨批遗漏关系，对标 step3 跨组补充）
    step1_cross_batch_done: bool = False
    step1_cross_batch_relations: List[Dict[str, Any]] = []
    step1_failed_batch: int = -1
    step1_failed_reason: Optional[str] = None

    # ── 文档解析后的自动摘要与构建规划（阶段 0 收尾自动生成，推送聊天供用户参考）──
    # LLM 生成的文档总结摘要（展示给用户，帮助决策）
    step0_summary: str = ""
    # LLM 给出的下一步构建建议（预计层级规模、从哪开始）
    step0_suggestion: str = ""
    # 构建规划：LLM 参与决策的分批方案，step1 提取时优先使用
    # 格式: [{"titles": ["第二章 物理域对象模型"], "target_chars": 9000}]，标题匹配由后端解析为文本区间
    step1_plan: List[Dict[str, Any]] = []
    # LLM 生成的层级提示（解析阶段识别的顶层父类建议，注入 step1 prompt）
    step1_hierarchy_hint: str = ""

    # Step 2 分批状态（长文档分批提取实体，支持断点续作）
    step2_batches_total: int = 0
    step2_batches_done: int = 0
    step2_batch_results: List[List[Dict[str, Any]]] = []
    # v3 新增：每批次的实例间关系（与 step2_batch_results 同长度，同索引对齐）
    step2_batch_relations_results: List[List[Dict[str, Any]]] = []
    step2_failed_batch: int = -1
    step2_failed_reason: Optional[str] = None

    # 返工记录：每次返工追加一条（step + 提示词 + 时间）
    rework_history: List[Dict[str, Any]] = []

    # AI 构建聊天历史（每轮对话追加一条；kind: text | summary | tool_result）
    # 结构：{"id","role":"user|assistant|tool","kind","content","payload","created_at"}
    chat_history: List[Dict[str, Any]] = []

    # 较早聊天历史的滚动摘要（增量更新，独立于 chat_history 原文，防止上下文超窗）
    history_summary: str = ""

    # ── 旧字段保留（向后兼容 v2 五阶段任务，新流程不使用）──
    meta_entity_types: List[Dict[str, Any]] = []          # v2 step0 本体模型（v3 弃用）
    meta_relation_types: List[Dict[str, Any]] = []        # v2 step0 关系类型（v3 弃用）
    meta_confirmed: bool = False                          # 阶段0「文档解析/配置」已确认（复用旧字段名，避免迁移）
    step1_concepts: List[Dict[str, Any]] = []             # v2 step1 实体类型（v3 迁移到 step1_entity_types）
    step3_relations: List[Dict[str, Any]] = []            # v2 step3 关系（v3 迁移到 step2_relations）
    step3_confirmed_legacy: bool = False                  # v2 step3 确认
    step4_verification: Optional[Dict[str, Any]] = None   # v2 step4 验证（v3 迁移到 step3_verification）
    step4_report: Optional[str] = None                    # v2 step4 报告（v3 迁移到 step3_report）
    step4_confirmed: bool = False                         # v2 step4 确认
    primary_entity_candidates: List[str] = []             # v2 主要实体候选（v3 弃用）
    primary_entity_selected: List[str] = []               # v2 主要实体勾选（v3 弃用）
    step1_failed_batch_legacy: int = -1                   # v2 备份
    step1_failed_reason_legacy: Optional[str] = None
    step2_failed_batch_legacy: int = -1
    step2_failed_reason_legacy: Optional[str] = None
    step3_groups_total: int = 0                           # v2 step3 分组（v3 弃用）
    step3_groups_done: int = 0
    step3_group_results: List[Dict[str, Any]] = []
    step3_failed_group: int = -1
    step3_failed_reason: Optional[str] = None
    step3_cross_group_done: bool = False
    step3_cross_group_relations: List[Dict[str, Any]] = []
    step3_cross_group_failed: bool = False
    step3_cross_group_reason: Optional[str] = None

    # 关联正式本体（step3 确认后生成）
    ontology_id: Optional[str] = None

    # 后台任务进度跟踪
    running_step: int = -1                     # -1=空闲, 0=文档解析, 1=类型提取, 2=实体提取, 3=分析验证
    progress: int = 0                          # 0-100
    progress_message: str = ""
    progress_stages: List[Dict[str, Any]] = []  # 真实进度：[{name, status, started_at, finished_at}]
    error_message: Optional[str] = None

    create_time: datetime
    update_time: datetime


# ──────────────────────────────────────────────────────────────────
# 向后兼容别名（v3 删除 ConceptType / TemplateConceptSchema，
# 但旧代码引用仍可工作：EntityType 通过 @property 兼容 entity_type /
# parent_concept_id / parent_concept_name 三个读取属性，
# 构造时传入这些 kwarg 会被 pydantic 默认 extra=ignore 静默丢弃，
# 不影响实例化。）
# ──────────────────────────────────────────────────────────────────
ConceptType = EntityType               # 旧 ConceptType → 新 EntityType
TemplateConceptSchema = TemplateEntityTypeSchema


def get_inherited_property_schema(
    entity_type: EntityType,
    all_types: List[EntityType],
) -> List[PropertySchema]:
    """计算实体类型的继承属性骨架（并集，按 name 去重）。

    v3 属性继承机制：子类型自动继承父类型的 property_schema，
    在运行时合并为并集（按 name 去重，子类型同名属性覆盖父类型）。

    Args:
        entity_type: 目标实体类型
        all_types: 本体内所有 EntityType（用于查找父类型链）

    Returns:
        合并后的 PropertySchema 列表（先父后子，子覆盖父同名属性）
    """
    # 按 id 建索引
    type_map = {t.id: t for t in all_types}

    # 自底向上收集父类型链（含自身）：[root_parent, ..., parent, self]
    chain: List[EntityType] = []
    seen_ids = set()  # 防循环引用
    cur = entity_type
    while cur and cur.id not in seen_ids:
        seen_ids.add(cur.id)
        chain.append(cur)
        parent_id = cur.parent_entity_type_id
        if not parent_id:
            break
        cur = type_map.get(parent_id)
    chain.reverse()  # 根在前，自身在后

    # 并集去重：根属性先入，子类型同名覆盖
    merged: Dict[str, PropertySchema] = {}
    for t in chain:
        for ps in t.property_schema:
            merged[ps.name] = ps
    return list(merged.values())
