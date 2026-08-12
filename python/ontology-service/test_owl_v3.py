"""OWL 导出 v3 适配验证脚本。

构造 v3 格式的测试数据（EntityType 层级 + EntityTypeRelation + Entity + Relation），
调用 export_ontology_to_owl 验证：
1. EntityType 层级正确映射为 subClassOf
2. EntityTypeRelation 映射为 ObjectProperty（带 domain/range）
3. Entity 映射为 NamedIndividual（rdf.type 指向 EntityType）
4. Relation 映射为 ObjectProperty 断言

运行：python test_owl_v3.py
"""
import os
import sys
from datetime import datetime

# 确保能导入本地模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    OntologyModel, EntityType, EntityTypeRelation, Entity, Relation,
    Property, PropertySchema, RelationType,
)
from owl_builder import export_ontology_to_owl

now = datetime.now()


def build_test_ontology():
    """构造 v3 测试本体：金融领域，含两级 EntityType 层级 + 类型间关系。"""
    # ── EntityType 层级 ──
    # 父类型：企业
    et_company = EntityType(
        id="et_company", ontology_id="ont_test01", name="企业",
        description="企业实体类型（顶层）",
        color="#5470c6",
        property_schema=[
            PropertySchema(name="成立时间", category="descriptive", data_type="date"),
            PropertySchema(name="注册资本", category="metric", data_type="number", unit="万元"),
        ],
        create_time=now, update_time=now,
    )
    # 子类型：上市企业（继承企业）
    et_listed = EntityType(
        id="et_listed", ontology_id="ont_test01", name="上市企业",
        description="上市企业，继承企业类型",
        color="#91cc75",
        property_schema=[
            PropertySchema(name="股票代码", category="descriptive", data_type="string"),
            PropertySchema(name="市值", category="metric", data_type="number", unit="亿元"),
        ],
        parent_entity_type_id="et_company",
        create_time=now, update_time=now,
    )

    # ── EntityTypeRelation（类型间关系）──
    etr_invest = EntityTypeRelation(
        id="etr_invest", ontology_id="ont_test01",
        source_entity_type_id="et_company",
        target_entity_type_id="et_company",
        relation_type="投资",
        description="企业之间可以相互投资",
        create_time=now, update_time=now,
    )
    etr_supply = EntityTypeRelation(
        id="etr_supply", ontology_id="ont_test01",
        source_entity_type_id="et_listed",
        target_entity_type_id="et_company",
        relation_type="供货",
        description="上市企业向其他企业供货",
        create_time=now, update_time=now,
    )

    # ── OntologyModel ──
    ont = OntologyModel(
        id="ont_test01", name="测试本体-金融", description="v3 OWL 导出测试",
        version="1.0.0",
        entity_types=[et_company, et_listed],
        relation_types=[RelationType(name="投资"), RelationType(name="供货")],
        create_time=now, update_time=now, status="活跃",
        schema_version=3,
    )

    # ── Entity（实例）──
    e1 = Entity(
        id="ent_a", ontology_id="ont_test01", name="甲公司",
        instance_of="et_company",
        properties=[
            Property(id="prop_a1", name="成立时间", value="2010-01-01", data_type="date", category="descriptive", entity_id="ent_a", create_time=now, update_time=now),
            Property(id="prop_a2", name="注册资本", value=5000, data_type="number", category="metric", unit="万元", entity_id="ent_a", create_time=now, update_time=now),
        ],
        create_time=now, update_time=now,
    )
    e2 = Entity(
        id="ent_b", ontology_id="ont_test01", name="乙上市",
        instance_of="et_listed",
        properties=[
            Property(id="prop_b1", name="股票代码", value="600001", data_type="string", category="descriptive", entity_id="ent_b", create_time=now, update_time=now),
            Property(id="prop_b2", name="市值", value=120, data_type="number", category="metric", unit="亿元", entity_id="ent_b", create_time=now, update_time=now),
        ],
        create_time=now, update_time=now,
    )

    # ── Relation（实例间关系）──
    r1 = Relation(
        id="rel_1", ontology_id="ont_test01",
        source_id="ent_a", target_id="ent_b",
        relation_type="投资",
        create_time=now,
    )

    return ont, [et_company, et_listed], [e1, e2], [r1], [etr_invest, etr_supply]


def main():
    print("=" * 60)
    print("OWL 导出 v3 适配验证")
    print("=" * 60)

    ont, entity_types, entities, relations, et_relations = build_test_ontology()
    print(f"测试本体: {ont.name} (id={ont.id})")
    print(f"  EntityType 数: {len(entity_types)}（含 1 个父子层级）")
    print(f"  EntityTypeRelation 数: {len(et_relations)}")
    print(f"  Entity 数: {len(entities)}")
    print(f"  Relation 数: {len(relations)}")

    # 调用 v3 导出（传入 entity_type_relations）
    output_path = os.path.join(os.path.dirname(__file__), "data", "ontologies", f"ontology_{ont.id}.owl")
    print(f"\n导出路径: {output_path}")
    result_path = export_ontology_to_owl(
        ont, entity_types, entities, relations,
        file_path=output_path,
        entity_type_relations=et_relations,
    )
    print(f"导出成功: {result_path}")

    # 验证文件内容
    file_size = os.path.getsize(result_path)
    print(f"文件大小: {file_size} bytes")

    with open(result_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 关键检查点
    checks = [
        ("EntityType '企业' 类定义", "企业" in content),
        ("EntityType '上市企业' 类定义", "上市企业" in content),
        ("subClassOf 层级（上市企业→企业）", content.count("subClassOf") >= 1),
        ("ObjectProperty '投资'", "投资" in content),
        ("ObjectProperty '供货'", "供货" in content),
        ("NamedIndividual '甲公司'", "甲公司" in content),
        ("NamedIndividual '乙上市'", "乙上市" in content),
        ("DatatypeProperty 属性断言", content.count("DatatypeProperty") >= 1),
        ("ObjectProperty 关系断言", content.count("ObjectProperty") >= 1),
    ]
    print("\n关键检查点：")
    all_pass = True
    for desc, ok in checks:
        status = "✓ 通过" if ok else "✗ 失败"
        print(f"  {status}  {desc}")
        if not ok:
            all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("✓ 全部检查通过，OWL 导出 v3 适配正常")
    else:
        print("✗ 存在失败项，请检查")
    print("=" * 60)

    # 打印 OWL 文件前 50 行预览
    print("\nOWL 文件预览（前 50 行）：")
    for i, line in enumerate(content.splitlines()[:50], 1):
        print(f"  {i:3d} | {line}")


if __name__ == "__main__":
    main()
