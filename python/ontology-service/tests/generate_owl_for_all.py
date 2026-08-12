"""对 data/user_ontologies/ 下所有现有本体生成 .owl 文件并做统计校验。

用法：
    cd python/ontology-service
    python -m tests.generate_owl_for_all

输出：
    data/ontologies/ontology_{id}.owl
    控制台打印每个本体的统计信息（class/individual/property 数）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import owlready2
from models import OntologyModel, ConceptType, Entity, Relation
from owl_builder import OwlBuilder

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
USER_ONT_DIR = os.path.join(DATA_DIR, "user_ontologies")
OUTPUT_DIR = os.path.join(DATA_DIR, "ontologies")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = sorted([
        f for f in os.listdir(USER_ONT_DIR)
        if f.startswith("ontology_") and f.endswith(".json")
    ])

    if not files:
        print("无现有本体 JSON 文件")
        return

    print(f"发现 {len(files)} 个本体文件")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 70)

    builder = OwlBuilder(output_dir=OUTPUT_DIR)
    total_stats = {
        "ontologies": 0,
        "classes": 0,
        "individuals": 0,
        "data_props": 0,
        "obj_props": 0,
        "data_assertions": 0,
        "obj_assertions": 0,
        "errors": 0,
    }

    for fname in files:
        fpath = os.path.join(USER_ONT_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)

            ont = OntologyModel(**data["ontology"])
            concepts = [ConceptType(**c) for c in data.get("concepts", [])]
            entities = [Entity(**e) for e in data.get("entities", [])]
            relations = [Relation(**r) for r in data.get("relations", [])]

            # 构建并保存
            out_path = os.path.join(OUTPUT_DIR, f"ontology_{ont.id}.owl")
            builder.build_and_save(
                ont, concepts, entities, relations,
                file_path=out_path
            )

            # 重新加载校验
            world = owlready2.World()
            loaded = world.get_ontology(f"file://{out_path}").load()

            classes_n = len(list(loaded.classes()))
            inds_n = len(list(loaded.individuals()))
            dp_n = len(list(loaded.data_properties()))
            op_n = len(list(loaded.object_properties()))

            dp_assertions = 0
            for dp in loaded.data_properties():
                for s in loaded.individuals():
                    vals = getattr(s, dp.python_name, None)
                    if vals:
                        if not isinstance(vals, list):
                            vals = [vals]
                        dp_assertions += len(vals)

            op_assertions = 0
            for op in loaded.object_properties():
                for s in loaded.individuals():
                    vals = getattr(s, op.python_name, None)
                    if vals:
                        if not isinstance(vals, list):
                            vals = [vals]
                        op_assertions += len(vals)

            file_size = os.path.getsize(out_path)

            print(f"\n[{ont.id}] {ont.name}")
            print(f"  源数据: {len(concepts)} 概念, {len(entities)} 实体, "
                  f"{len(relations)} 关系")
            print(f"  OWL:    {classes_n} class, {inds_n} individual, "
                  f"{dp_n} dataProp, {op_n} objProp")
            print(f"  断言:   {dp_assertions} 数据属性断言, "
                  f"{op_assertions} 关系断言")
            print(f"  文件:   {out_path} ({file_size} bytes)")

            total_stats["ontologies"] += 1
            total_stats["classes"] += classes_n
            total_stats["individuals"] += inds_n
            total_stats["data_props"] += dp_n
            total_stats["obj_props"] += op_n
            total_stats["data_assertions"] += dp_assertions
            total_stats["obj_assertions"] += op_assertions

        except Exception as e:
            total_stats["errors"] += 1
            print(f"\n[ERROR] {fname}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("汇总统计:")
    for k, v in total_stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
