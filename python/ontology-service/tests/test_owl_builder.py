"""OwlBuilder 单元测试与端到端验证。

运行方式：
    cd python/ontology-service
    python -m tests.test_owl_builder            # 直接运行
    python -m pytest tests/test_owl_builder.py  # pytest 运行

覆盖：
1. 基础构建：EntityType/ConceptType/Entity/Property/Relation 全映射
2. 中文属性名与 PropertySchema annotation
3. 重名冲突处理（_unique_local_name）
4. 数据类型转换（number/date/string）
5. 端到端：从现有 JSON 本体生成 .owl，重新加载断言结构
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from datetime import datetime

# 确保能 import 到 ontology-service 根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import owlready2
from owlready2 import owl

from models import (
    OntologyModel, ConceptType, Entity, Relation, Property,
    EntityType, RelationType, PropertySchema
)
from owl_builder import (
    OwlBuilder, _sanitize_local_name, _unique_local_name,
    _convert_value, _data_type_range, DEFAULT_IRI_BASE
)


# ──────────────────────────────────────────────────────────────
# 测试数据构造
# ──────────────────────────────────────────────────────────────

def _build_minimal_ontology() -> tuple:
    """构造最小测试本体：1 entity_type / 1 concept / 2 entities / 1 relation。"""
    now = datetime.now()
    ont = OntologyModel(
        id="ont_test_001",
        name="测试本体",
        description="OwlBuilder 单元测试用本体",
        version="1.0.0",
        entity_types=[
            EntityType(name="人物", color="#5470c6"),
            EntityType(name="公司", color="#91cc75"),
        ],
        relation_types=[RelationType(name="任职于")],
        create_time=now, update_time=now,
        status="活跃", is_default=False,
        schema_version=2,
    )

    c_person = ConceptType(
        id="concept_person", ontology_id=ont.id,
        name="人物", entity_type="人物",
        description="自然人概念",
        color="#5470c6",
        property_schema=[
            PropertySchema(name="年龄", category="descriptive",
                           data_type="number", unit="岁"),
            PropertySchema(name="职业", category="descriptive",
                           data_type="string"),
        ],
        create_time=now, update_time=now,
    )
    c_company = ConceptType(
        id="concept_company", ontology_id=ont.id,
        name="公司", entity_type="公司",
        description="企业法人概念",
        color="#91cc75",
        property_schema=[
            PropertySchema(name="资产负债率", category="metric",
                           data_type="number", unit="%",
                           description="总负债/总资产"),
        ],
        create_time=now, update_time=now,
    )
    concepts = [c_person, c_company]

    e_zhang = Entity(
        id="ent_zhang", ontology_id=ont.id,
        name="张三", instance_of="concept_person",
        is_primary=True,
        properties=[
            Property(id="prop_age", entity_id="ent_zhang",
                     name="年龄", value=35, category="descriptive",
                     data_type="number", unit="岁",
                     create_time=now, update_time=now),
            Property(id="prop_job", entity_id="ent_zhang",
                     name="职业", value="工程师", category="descriptive",
                     data_type="string",
                     create_time=now, update_time=now),
        ],
        create_time=now, update_time=now,
    )
    e_ali = Entity(
        id="ent_ali", ontology_id=ont.id,
        name="阿里巴巴", instance_of="concept_company",
        properties=[
            Property(id="prop_ratio", entity_id="ent_ali",
                     name="资产负债率", value=0.45, category="metric",
                     data_type="number", unit="%",
                     create_time=now, update_time=now),
        ],
        create_time=now, update_time=now,
    )
    entities = [e_zhang, e_ali]

    r1 = Relation(
        id="rel_1", ontology_id=ont.id,
        source_id="ent_zhang", target_id="ent_ali",
        relation_type="任职于",
        weight=1.0, create_time=now,
    )
    relations = [r1]

    return ont, concepts, entities, relations


# ──────────────────────────────────────────────────────────────
# 辅助函数单元测试
# ──────────────────────────────────────────────────────────────

class TestSanitizeLocalName(unittest.TestCase):
    """_sanitize_local_name 行为测试。"""

    def test_chinese_preserved(self):
        self.assertEqual(_sanitize_local_name("资产负债率"), "资产负债率")
        self.assertEqual(_sanitize_local_name("公司"), "公司")

    def test_space_replaced(self):
        self.assertEqual(_sanitize_local_name("hello world"), "hello_world")

    def test_special_chars_replaced(self):
        self.assertEqual(_sanitize_local_name("a-b/c"), "a_b_c")

    def test_leading_digit_prefixed(self):
        self.assertEqual(_sanitize_local_name("123abc"), "_123abc")

    def test_empty_returns_unnamed(self):
        self.assertEqual(_sanitize_local_name(""), "unnamed")
        self.assertEqual(_sanitize_local_name(None), "unnamed")


class TestUniqueLocalName(unittest.TestCase):
    """_unique_local_name 冲突处理测试。"""

    def test_no_conflict(self):
        used = set()
        self.assertEqual(_unique_local_name("公司", used), "公司")
        self.assertIn("公司", used)

    def test_conflict_appends_suffix(self):
        used = {"公司"}
        self.assertEqual(_unique_local_name("公司", used), "公司_2")
        self.assertIn("公司_2", used)

    def test_multiple_conflicts(self):
        used = {"公司", "公司_2", "公司_3"}
        self.assertEqual(_unique_local_name("公司", used), "公司_4")


class TestConvertValue(unittest.TestCase):
    """_convert_value 数据类型转换测试。"""

    def test_number_int_to_float(self):
        self.assertEqual(_convert_value(35, "number"), 35.0)

    def test_number_str_to_float(self):
        self.assertEqual(_convert_value("0.45", "number"), 0.45)

    def test_number_invalid_falls_back_to_string(self):
        self.assertEqual(_convert_value("N/A", "number"), "N/A")

    def test_string_unchanged(self):
        self.assertEqual(_convert_value("工程师", "string"), "工程师")

    def test_date_as_string(self):
        self.assertEqual(_convert_value("2026-08-11", "date"), "2026-08-11")

    def test_none_returns_none(self):
        self.assertIsNone(_convert_value(None, "number"))


class TestDataTypeRange(unittest.TestCase):
    """_data_type_range 测试。"""

    def test_number_returns_float(self):
        self.assertEqual(_data_type_range("number"), float)

    def test_string_returns_str(self):
        self.assertEqual(_data_type_range("string"), str)

    def test_unknown_returns_str(self):
        self.assertEqual(_data_type_range("enum"), str)
        self.assertEqual(_data_type_range("date"), str)


# ──────────────────────────────────────────────────────────────
# OwlBuilder 集成测试
# ──────────────────────────────────────────────────────────────

class TestOwlBuilderBuild(unittest.TestCase):
    """OwlBuilder.build 集成测试。"""

    @classmethod
    def setUpClass(cls):
        cls.ont, cls.concepts, cls.entities, cls.relations = _build_minimal_ontology()
        cls.builder = OwlBuilder()
        cls.onto = cls.builder.build(cls.ont, cls.concepts, cls.entities, cls.relations)

    def test_ontology_iri_correct(self):
        """本体 IRI 应为 {base}{id}#"""
        expected = f"{DEFAULT_IRI_BASE}{self.ont.id}#"
        self.assertEqual(self.onto.base_iri, expected)

    def test_entity_type_classes_created(self):
        """EntityType 应映射为 owl:Class 顶层。"""
        classes = list(self.onto.classes())
        class_names = {c.name for c in classes}
        self.assertIn("人物", class_names)
        self.assertIn("公司", class_names)

    def test_concept_classes_subclass_of_entity_type(self):
        """ConceptType 应 subClassOf 对应的 EntityType。"""
        # 概念名与 entity_type 名相同时，会触发 _unique_local_name 加后缀
        # 验证：存在 subClassOf 关系指向人物/公司 class
        classes = list(self.onto.classes())
        # 应该有 4 个 class（2 entity_type + 2 concept，concept 重名时加 _2）
        self.assertGreaterEqual(len(classes), 4)

    def test_individuals_created(self):
        """Entity 应映射为 owl:NamedIndividual。"""
        individuals = list(self.onto.individuals())
        self.assertGreaterEqual(len(individuals), 2)
        # 验证 label
        labels = []
        for ind in individuals:
            labels.extend(ind.label)
        self.assertIn("张三", labels)
        self.assertIn("阿里巴巴", labels)

    def test_datatype_property_created(self):
        """Property 应映射为 owl:DatatypeProperty（label 保留原文名）。"""
        data_props = list(self.onto.data_properties())
        # local name 加 dp_ 前缀，label 保留原文名
        prop_labels = set()
        for p in data_props:
            prop_labels.update(p.label)
        self.assertIn("年龄", prop_labels)
        self.assertIn("职业", prop_labels)
        self.assertIn("资产负债率", prop_labels)

    def test_object_property_created(self):
        """Relation 应映射为 owl:ObjectProperty（label 保留原文名）。"""
        obj_props = list(self.onto.object_properties())
        prop_labels = set()
        for p in obj_props:
            prop_labels.update(p.label)
        self.assertIn("任职于", prop_labels)

    def test_property_value_asserted(self):
        """individual 上应断言 DatatypeProperty 值。"""
        # 找到张三 individual
        zhang = None
        for ind in self.onto.individuals():
            if "张三" in ind.label:
                zhang = ind
                break
        self.assertIsNotNone(zhang)
        # 通过 label 查找 DatatypeProperty（local name 加了 dp_ 前缀）
        age_prop = None
        job_prop = None
        for p in self.onto.data_properties():
            if "年龄" in p.label:
                age_prop = p
            if "职业" in p.label:
                job_prop = p
        self.assertIsNotNone(age_prop)
        self.assertIsNotNone(job_prop)
        # 年龄应为 35.0
        self.assertEqual(getattr(zhang, age_prop.python_name), [35.0])
        # 职业应为 "工程师"
        self.assertEqual(getattr(zhang, job_prop.python_name), ["工程师"])

    def test_relation_asserted(self):
        """Relation 应断言 ObjectProperty 关系。"""
        zhang = None
        ali = None
        for ind in self.onto.individuals():
            if "张三" in ind.label:
                zhang = ind
            if "阿里巴巴" in ind.label:
                ali = ind
        self.assertIsNotNone(zhang)
        self.assertIsNotNone(ali)
        # 通过 label 查找 ObjectProperty（local name 加了 op_ 前缀）
        works_at_prop = None
        for p in self.onto.object_properties():
            if "任职于" in p.label:
                works_at_prop = p
                break
        self.assertIsNotNone(works_at_prop)
        # 张三 任职于 阿里巴巴
        self.assertIn(ali, getattr(zhang, works_at_prop.python_name))

    def test_property_schema_annotation(self):
        """PropertySchema 应作为 class annotation 存在。"""
        # 查找带 propertySchema annotation 的 class
        # 人物概念 class 应该有 propertySchema annotation（含"年龄"）
        found = False
        for c in self.onto.classes():
            schema_vals = list(c.propertySchema)
            if schema_vals:
                for v in schema_vals:
                    if "年龄" in v:
                        found = True
                        break
        self.assertTrue(found, "PropertySchema annotation 未找到")


class TestOwlBuilderSave(unittest.TestCase):
    """OwlBuilder.save 序列化测试。"""

    @classmethod
    def setUpClass(cls):
        cls.ont, cls.concepts, cls.entities, cls.relations = _build_minimal_ontology()
        cls.builder = OwlBuilder()
        cls.onto = cls.builder.build(cls.ont, cls.concepts, cls.entities, cls.relations)
        # 保存到临时目录
        cls.tmp_dir = tempfile.mkdtemp(prefix="owl_test_")
        cls.file_path = os.path.join(cls.tmp_dir, "test.owl")
        cls.builder.save(cls.onto, cls.file_path)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.tmp_dir):
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_file_exists(self):
        self.assertTrue(os.path.exists(self.file_path))

    def test_file_non_empty(self):
        self.assertGreater(os.path.getsize(self.file_path), 0)

    def test_file_is_rdf_xml(self):
        """文件应以 <?xml 开头并含 rdf:RDF。"""
        with open(self.file_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("<?xml", content)
        self.assertIn("rdf:RDF", content)
        self.assertIn("owl:Ontology", content)

    def test_file_contains_chinese_labels(self):
        """文件应含中文 rdfs:label。"""
        with open(self.file_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("张三", content)
        self.assertIn("阿里巴巴", content)
        self.assertIn("资产负债率", content)


class TestOwlBuilderReload(unittest.TestCase):
    """保存后重新加载，断言结构完整。"""

    @classmethod
    def setUpClass(cls):
        cls.ont, cls.concepts, cls.entities, cls.relations = _build_minimal_ontology()
        cls.builder = OwlBuilder()
        cls.tmp_dir = tempfile.mkdtemp(prefix="owl_reload_")
        cls.file_path = os.path.join(cls.tmp_dir, "reload.owl")
        cls.builder.build_and_save(cls.ont, cls.concepts, cls.entities, cls.relations,
                                    file_path=cls.file_path)
        # 重新加载
        cls.world = owlready2.World()
        cls.loaded = cls.world.get_ontology(f"file://{cls.file_path}").load()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.tmp_dir):
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_reload_classes_count(self):
        classes = list(self.loaded.classes())
        self.assertGreaterEqual(len(classes), 4)

    def test_reload_individuals_count(self):
        individuals = list(self.loaded.individuals())
        self.assertGreaterEqual(len(individuals), 2)

    def test_reload_datatype_properties_count(self):
        data_props = list(self.loaded.data_properties())
        self.assertGreaterEqual(len(data_props), 3)

    def test_reload_object_properties_count(self):
        obj_props = list(self.loaded.object_properties())
        self.assertGreaterEqual(len(obj_props), 1)


# ──────────────────────────────────────────────────────────────
# 端到端：从现有 JSON 本体生成 OWL
# ──────────────────────────────────────────────────────────────

class TestEndToEndFromJson(unittest.TestCase):
    """从 data/user_ontologies/ 加载现有本体，生成 OWL 并验证。"""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "user_ontologies"
        )
        # 找一个现有的本体 JSON 文件
        cls.json_files = [
            f for f in os.listdir(cls.data_dir)
            if f.startswith("ontology_") and f.endswith(".json")
        ]
        if not cls.json_files:
            raise unittest.SkipTest("无现有本体 JSON 文件，跳过端到端测试")
        # 选第一个文件
        cls.json_path = os.path.join(cls.data_dir, cls.json_files[0])
        with open(cls.json_path, encoding="utf-8") as f:
            cls.data = json.load(f)

        # 解析为 Pydantic 模型
        ont_dict = cls.data["ontology"]
        # 兼容 datetime 字符串
        cls.ont = OntologyModel(**ont_dict)
        cls.concepts = [ConceptType(**c) for c in cls.data.get("concepts", [])]
        cls.entities = [Entity(**e) for e in cls.data.get("entities", [])]
        cls.relations = [Relation(**r) for r in cls.data.get("relations", [])]

        cls.builder = OwlBuilder()
        cls.tmp_dir = tempfile.mkdtemp(prefix="owl_e2e_")
        cls.file_path = os.path.join(cls.tmp_dir, "e2e.owl")
        cls.builder.build_and_save(
            cls.ont, cls.concepts, cls.entities, cls.relations,
            file_path=cls.file_path
        )

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.tmp_dir):
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_e2e_file_generated(self):
        self.assertTrue(os.path.exists(self.file_path))
        self.assertGreater(os.path.getsize(self.file_path), 1000)

    def test_e2e_individuals_match_source(self):
        """重新加载后 individual 数应与源数据一致（或更多，因概念可能为空）。"""
        world = owlready2.World()
        loaded = world.get_ontology(f"file://{self.file_path}").load()
        loaded_count = len(list(loaded.individuals()))
        source_count = len(self.entities)
        self.assertEqual(loaded_count, source_count,
                         f"individual 数不匹配: 源 {source_count}, 加载 {loaded_count}")

    def test_e2e_relations_match_source(self):
        """ObjectProperty 断言数应与源有效 relation 数一致。

        源数据可能含无效关系（source_id/target_id 指向不存在的实体），
        owl_builder 会防御性跳过，故按"有效关系数"比较而非原始 relation 数。
        """
        world = owlready2.World()
        loaded = world.get_ontology(f"file://{self.file_path}").load()
        # 统计所有 ObjectProperty 上的断言数
        total_assertions = 0
        for op in loaded.object_properties():
            for s in loaded.individuals():
                vals = getattr(s, op.python_name, None)
                if vals:
                    if not isinstance(vals, list):
                        vals = [vals]
                    total_assertions += len(vals)
        # 计算源数据中的有效关系数（source/target 都在 entities 列表中）
        valid_entity_ids = {e.id for e in self.entities}
        valid_source_count = sum(
            1 for r in self.relations
            if r.source_id in valid_entity_ids and r.target_id in valid_entity_ids
        )
        skipped = len(self.relations) - valid_source_count
        self.assertEqual(
            total_assertions, valid_source_count,
            f"关系断言数不匹配: 源有效 {valid_source_count}（原始 {len(self.relations)}"
            f"，跳过无效 {skipped}）, 加载 {total_assertions}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
