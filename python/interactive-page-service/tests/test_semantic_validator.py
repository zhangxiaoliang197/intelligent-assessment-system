"""语义注解校验测试：与 Java 侧共用同一份 schema 与 golden 用例。

用例文件位置（仓库内相对路径）：
- 格式规范：java/admin-service/src/main/resources/semantic-schema.json（单一真相）
- golden 用例：tests/fixtures/semantic_cases.json（与 SemanticSchemaValidatorTest 共用）
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import semantic_validator

_SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SERVICE_DIR))
_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "java", "admin-service", "src", "main", "resources", "semantic-schema.json")
_CASES_PATH = os.path.join(_REPO_ROOT, "tests", "fixtures", "semantic_cases.json")


class SemanticValidatorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            cls.schema_text = f.read()
        with open(_CASES_PATH, "r", encoding="utf-8") as f:
            cls.cases = json.load(f)

    def test_schema_should_be_loadable_from_admin_resource(self):
        """格式规范来自 admin 侧同一份文件，两端不存在第二份拷贝。"""
        self.assertTrue(semantic_validator.set_schema(self.schema_text))
        self.assertTrue(semantic_validator.is_available())

    def test_missing_schema_means_unavailable(self):
        """未收到 schema 时不得静默当成通过，必须可被调用方识别。"""
        saved = semantic_validator._field_validator
        semantic_validator._field_validator = None
        try:
            self.assertFalse(semantic_validator.is_available())
            self.assertEqual([], semantic_validator.validate_field({"role": "name"}))
        finally:
            semantic_validator._field_validator = saved

    def test_dataset_golden_cases(self):
        self.assertTrue(semantic_validator.set_schema(self.schema_text))
        self._assert_cases("dataset", semantic_validator.validate_dataset)

    def test_field_golden_cases(self):
        self.assertTrue(semantic_validator.set_schema(self.schema_text))
        self._assert_cases("field", semantic_validator.validate_field)

    def _assert_cases(self, section, validate_fn):
        cases = self.cases.get(section) or []
        self.assertTrue(cases, f"用例文件缺少 {section} 分组")
        for case in cases:
            with self.subTest(case=case["name"]):
                errors = validate_fn(case["value"])
                self.assertEqual(
                    case["valid"], not errors,
                    f"用例「{case['name']}」判定与预期不符，错误明细={errors}")

    def test_blank_means_unconfigured(self):
        self.assertTrue(semantic_validator.set_schema(self.schema_text))
        for blank in (None, "", "   "):
            self.assertEqual([], semantic_validator.validate_field(blank))
            self.assertEqual([], semantic_validator.validate_dataset(blank))

    def test_invalid_json_must_be_reported(self):
        self.assertTrue(semantic_validator.set_schema(self.schema_text))
        self.assertEqual(1, len(semantic_validator.validate_field("{不是 json")))
        self.assertEqual(1, len(semantic_validator.validate_dataset("[1,2]")))

    def test_schema_can_be_passed_as_dict_and_reused(self):
        parsed = json.loads(self.schema_text)
        self.assertTrue(semantic_validator.set_schema(parsed))
        # 重复注入同一份规范应复用校验器（元数据每次生成都会带 schema）
        first = semantic_validator._field_validator
        self.assertTrue(semantic_validator.set_schema(parsed))
        self.assertIs(first, semantic_validator._field_validator)


if __name__ == "__main__":
    unittest.main()
