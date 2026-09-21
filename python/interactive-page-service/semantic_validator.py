"""领域语义注解（semantic_json）的格式校验。

与 admin-service 的 ``SemanticSchemaValidator`` 同规则：格式规范只有一份
（admin 的 ``resources/semantic-schema.json``），由 ``/api/admin/export/for-llm``
随元数据下发，本模块从响应中的 ``semanticSchema`` 取用，避免两端各存一份漂移。

设计口径：
1. 校验结论与 Java 侧由 ``tests/fixtures/semantic_cases.json`` 双向断言，防止漂移；
2. jsonschema 未安装或 schema 未下发时 ``is_available()`` 为假，调用方须降级为
   只记录"未校验"，禁止静默当成通过（历史缺陷：无注解即静默跳过）；
3. 空值与空白视为"未配置语义"，合法。
"""
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("ipage-service")

try:  # 允许未安装依赖时降级（明确告警，不静默放行）
    import jsonschema
except ImportError:  # pragma: no cover - 由 requirements 保证安装
    jsonschema = None

# schema 原文（由元数据响应注入）
_schema_root: Optional[Dict[str, Any]] = None
_schema_fingerprint = ""
_field_validator: Any = None
_dataset_validator: Any = None
_unavailable_reason = "尚未收到 admin 下发的 semanticSchema"
_lock = threading.Lock()

_FIELD_REF = "fieldSemantic"
_DATASET_REF = "datasetSemantic"


def set_schema(root: Union[str, Dict[str, Any], None]) -> bool:
    """注入格式规范（admin 下发的 ``semanticSchema`` 原文或已解析字典）。

    同一份规范重复注入会直接复用已构建的校验器（元数据每次生成都会带 schema）。

    Returns:
        True 表示校验器就绪；False 表示仍不可用（原因见 unavailable_reason()）。
    """
    global _schema_root, _schema_fingerprint, _field_validator, _dataset_validator
    global _unavailable_reason
    if root is None or (isinstance(root, str) and not root.strip()):
        return False
    if jsonschema is None:
        with _lock:
            _unavailable_reason = "未安装 jsonschema 依赖"
        return False

    fingerprint = root if isinstance(root, str) else json.dumps(
        root, sort_keys=True, ensure_ascii=False)
    if fingerprint == _schema_fingerprint and _field_validator is not None:
        return True

    try:
        parsed = json.loads(root) if isinstance(root, str) else root
        if not isinstance(parsed, dict) or not isinstance(parsed.get("$defs"), dict):
            raise ValueError("schema 缺少 $defs")
        with _lock:
            _schema_root = parsed
            _field_validator = _build_sub_validator(parsed, _FIELD_REF)
            _dataset_validator = _build_sub_validator(parsed, _DATASET_REF)
            _schema_fingerprint = fingerprint
            _unavailable_reason = ""
        return True
    except Exception as exc:
        with _lock:
            _field_validator = None
            _dataset_validator = None
            _unavailable_reason = f"schema 解析失败: {exc}"
        logger.warning("解析 admin 下发的 semanticSchema 失败: %s", exc)
        return False


def _build_sub_validator(root: Dict[str, Any], def_name: str) -> Any:
    """按 ``$ref`` 构造子模式校验器；$defs 随节点带上以解析本地引用。"""
    sub = {"$ref": f"#/$defs/{def_name}", "$defs": root["$defs"]}
    validator_cls = jsonschema.validators.validator_for(sub, default=jsonschema.Draft202012Validator)
    return validator_cls(sub)


def is_available() -> bool:
    """校验器是否就绪。"""
    return _field_validator is not None and _dataset_validator is not None


def unavailable_reason() -> str:
    """不可用原因（就绪时为空串）。"""
    return _unavailable_reason


def validate_field(semantic: Union[str, Dict[str, Any], None]) -> List[str]:
    """校验字段级语义，返回中文错误条目（空列表表示通过或未配置）。"""
    return _validate(_field_validator, semantic, "字段级语义")


def validate_dataset(semantic: Union[str, Dict[str, Any], None]) -> List[str]:
    """校验数据集级语义，返回中文错误条目（空列表表示通过或未配置）。"""
    return _validate(_dataset_validator, semantic, "数据集级语义")


def _validate(validator: Any, semantic: Union[str, Dict[str, Any], None],
              label: str) -> List[str]:
    errors: List[str] = []
    if validator is None:
        return errors
    if semantic is None:
        return errors
    if isinstance(semantic, str):
        if not semantic.strip():
            return errors
        try:
            instance = json.loads(semantic)
        except Exception as exc:
            return [f"{label}不是合法 JSON：{exc}"]
    else:
        instance = semantic
    if instance is None or instance == "":
        return errors
    if not isinstance(instance, dict):
        return [f"{label}必须是 JSON 对象"]
    for err in validator.iter_errors(instance):
        path = "/".join(str(p) for p in err.absolute_path)
        errors.append(f"{label} {err.message}（路径 {path or '/'}）")
    return errors
