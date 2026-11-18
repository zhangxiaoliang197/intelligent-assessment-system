"""Fictional equipment exercise: four snapshots, OWL semantics and SHACL.

All names and scores are synthetic teaching data. The example models readiness,
coordination, maintenance and observations; it is not a weapon effects model.
"""
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS, OWL, XSD

DEMO_ID = "ont_demo_qinglan"
DEMO_NAME = "装备协同推演"
DEMO_DESCRIPTION = "内置样例：通过四个回合查看装备状态、编组协作、任务进度和评估溯源。"
LEGACY_NAME = "青岚行动 · 兵棋推演本体"
LEGACY_DESCRIPTION = "虚构装备协同推演示例；包含四个回合、OWL 等价类/限制/反向关系和 SHACL 约束。所有名称与数值均为教学合成数据。"
S = Namespace("https://example.org/qinglan/schema#")
E = Namespace("https://example.org/qinglan/equipment#")
U = Namespace("https://example.org/qinglan/unit#")
M = Namespace("https://example.org/qinglan/mission#")
F = Namespace("https://example.org/qinglan/force#")
T = Namespace("https://example.org/qinglan/turn#")
V = Namespace("https://example.org/qinglan/event#")
A = Namespace("https://example.org/qinglan/assessment#")
NAMESPACES = {"ql": str(S), "equip": str(E), "unit": str(U), "mission": str(M), "force": str(F), "turn": str(T), "event": str(V), "assess": str(A)}
TURNS = [
    {"index": 0, "time": "09:00", "title": "初始编组", "description": "登记装备、编组关系和任务初始状态。", "progress": 8, "readiness": 100, "coordination": 82},
    {"index": 1, "time": "09:15", "title": "状态变化", "description": "部分装备出现链路延迟，记录状态与任务进度变化。", "progress": 32, "readiness": 75, "coordination": 68},
    {"index": 2, "time": "09:30", "title": "协同处理", "description": "链路恢复，协作单元记录装备维护及进度。", "progress": 67, "readiness": 88, "coordination": 86},
    {"index": 3, "time": "09:45", "title": "推演复盘", "description": "汇总各回合变化，查看评估结果及其依据。", "progress": 100, "readiness": 100, "coordination": 93},
]
LEGACY_LABELS = {
    F.Blue: "蓝方 · 青岚演练方", F.Red: "红方 · 对照演练方",
    U.BlueTeam: "蓝方协同编组", U.BlueSupport: "蓝方保障单元", U.RedTeam: "红方对照编组",
    E.C01: "青岚 C-01 指挥车", E.C02: "赤砂 C-02 指挥车",
    E.R01: "青岚 R-01 观测平台", E.R02: "青岚 R-02 观测平台", E.R03: "赤砂 R-03 观测平台",
    E.G01: "青岚 G-01 地面平台", E.G02: "青岚 G-02 地面平台", E.L01: "青岚 L-01 保障车",
    S.Platform: "兵器装备", S.CommandVehicle: "指挥装备", S.SupportVehicle: "保障装备",
    S.Force: "演练方", S.Unit: "作战编组", S.Mission: "演练任务",
    S.commands: "指挥", S.commandedBy: "接受指挥", S.supports: "保障", M.Support: "装备保障任务",
    V.E0: "编组就绪", V.E1: "链路变化", V.E2: "保障协同",
}
LEGACY_NOTES = {
    V.E0: "建立装备、指挥关系与任务基线。",
    V.E1: "观测平台链路延迟，任务状态随回合更新。",
    V.E2: "链路恢复，保障单元开展维护并提升协同。",
    V.E3: "汇总任务状态，验证关系推导与评估溯源。",
}


def update_demo_metadata(metadata):
    if metadata.get("id") == DEMO_ID:
        if metadata.get("name") == LEGACY_NAME:
            metadata["name"] = DEMO_NAME
        if metadata.get("description") == LEGACY_DESCRIPTION:
            metadata["description"] = DEMO_DESCRIPTION


def update_demo_literals(graph, current_seed):
    changed = False
    for predicate, legacy in ((RDFS.label, LEGACY_LABELS), (S.note, LEGACY_NOTES)):
        for subject, value in list(graph.subject_objects(predicate)):
            if not isinstance(value, Literal):
                continue
            text = str(value)
            old_text = legacy.get(subject)
            strip_brand = predicate == RDFS.label and "青岚" in text
            if text != old_text and not strip_brand:
                continue
            current = current_seed.value(subject, predicate)
            if current is None:
                continue
            if text == old_text:
                replacement = str(current)
            elif old_text and text.startswith(old_text):
                replacement = (str(current) + text[len(old_text):]).replace("青岚", "").strip()
            else:
                replacement = text.replace("青岚", "").strip() or str(current)
            graph.remove((subject, predicate, value))
            graph.add((subject, predicate, Literal(replacement, lang=value.language, datatype=value.datatype)))
            changed = True
    return changed


def make_graph(turn=0):
    if turn not in range(4):
        raise ValueError("Turn must be between 0 and 3")
    g = Graph()
    for prefix, namespace in NAMESPACES.items():
        g.bind(prefix, namespace)
    for prefix, namespace in (("owl", OWL), ("rdf", RDF), ("rdfs", RDFS), ("xsd", XSD)):
        g.bind(prefix, namespace)

    def label(subject, value):
        g.add((subject, RDFS.label, Literal(value, lang="zh")))

    def node(subject, kind, name):
        g.add((subject, RDF.type, kind)); label(subject, name)
        return subject

    classes = [
        ("ExerciseObject", "推演对象", None), ("Platform", "装备", "ExerciseObject"),
        ("ReconPlatform", "观测装备", "Platform"), ("CommandVehicle", "调度装备", "Platform"),
        ("SupportVehicle", "维护装备", "Platform"), ("GroundPlatform", "地面装备", "Platform"),
        ("Force", "协作小组", "ExerciseObject"), ("Unit", "协作单元", "ExerciseObject"),
        ("Mission", "任务", "ExerciseObject"), ("ExerciseTurn", "推演回合", "ExerciseObject"),
        ("Event", "推演事件", "ExerciseObject"), ("Assessment", "体系评估", "ExerciseObject"),
        ("ReadyPlatform", "就绪装备〔可推导〕", "Platform"),
        ("SupportedUnit", "具备就绪装备的编组〔可推导〕", "Unit"),
    ]
    for key, name, parent in classes:
        node(S[key], OWL.Class, name)
        if parent: g.add((S[key], RDFS.subClassOf, S[parent]))
    relationships = [
        ("belongsTo", "隶属于", "ExerciseObject", "ExerciseObject"),
        ("hasPlatform", "编配装备", "Unit", "Platform"),
        ("commands", "调度", "CommandVehicle", "Unit"),
        ("commandedBy", "由其调度", "Unit", "CommandVehicle"),
        ("assignedTo", "承担任务", "Unit", "Mission"),
        ("supports", "提供维护", "SupportVehicle", "Unit"),
        ("observes", "提供观测", "ReconPlatform", "Mission"),
        ("affects", "影响对象", "Event", "ExerciseObject"),
        ("occurredIn", "发生于回合", "Event", "ExerciseTurn"),
        ("evaluates", "评估对象", "Assessment", "Unit"),
        ("derivedFrom", "依据事件", "Assessment", "Event"),
    ]
    for key, name, domain, range_ in relationships:
        node(S[key], OWL.ObjectProperty, name)
        g.add((S[key], RDFS.domain, S[domain])); g.add((S[key], RDFS.range, S[range_]))
    g.add((S.belongsTo, RDF.type, OWL.TransitiveProperty))
    g.add((S.commands, OWL.inverseOf, S.commandedBy))
    g.add((S.hasPlatform, OWL.inverseOf, S.belongsToUnit))
    node(S.belongsToUnit, OWL.ObjectProperty, "编配于")
    fields = [("status", "运行状态", XSD.string), ("progress", "任务进度", XSD.integer), ("score", "评估得分", XSD.integer), ("note", "推演说明", XSD.string), ("time", "推演时刻", XSD.string)]
    for key, name, range_ in fields:
        node(S[key], OWL.DatatypeProperty, name); g.add((S[key], RDFS.range, range_))

    # ReadyPlatform = Platform AND (status value "就绪").
    restriction = BNode("ready-status")
    g.add((restriction, RDF.type, OWL.Restriction)); g.add((restriction, OWL.onProperty, S.status))
    g.add((restriction, OWL.hasValue, Literal("就绪")))
    intersection = BNode("ready-intersection"); list1 = BNode("ready-list1"); list2 = BNode("ready-list2")
    g.add((S.ReadyPlatform, OWL.equivalentClass, intersection)); g.add((intersection, RDF.type, OWL.Class))
    g.add((intersection, OWL.intersectionOf, list1)); g.add((list1, RDF.first, S.Platform)); g.add((list1, RDF.rest, list2))
    g.add((list2, RDF.first, restriction)); g.add((list2, RDF.rest, RDF.nil))
    supported = BNode("supported-unit")
    g.add((supported, RDF.type, OWL.Restriction)); g.add((supported, OWL.onProperty, S.hasPlatform)); g.add((supported, OWL.someValuesFrom, S.ReadyPlatform))
    g.add((S.SupportedUnit, OWL.equivalentClass, supported))

    node(F.Blue, S.Force, "甲组"); node(F.Red, S.Force, "乙组")
    node(U.BlueTeam, S.Unit, "甲组协同单元"); node(U.BlueSupport, S.Unit, "甲组维护单元"); node(U.RedTeam, S.Unit, "乙组协同单元")
    g.add((U.BlueTeam, S.belongsTo, F.Blue)); g.add((U.BlueSupport, S.belongsTo, U.BlueTeam)); g.add((U.RedTeam, S.belongsTo, F.Red))
    platforms = [
        ("C01", "C-01 调度车", "CommandVehicle", U.BlueTeam),
        ("R01", "R-01 观测平台", "ReconPlatform", U.BlueTeam),
        ("R02", "R-02 观测平台", "ReconPlatform", U.BlueTeam),
        ("G01", "G-01 地面平台", "GroundPlatform", U.BlueTeam),
        ("G02", "G-02 地面平台", "GroundPlatform", U.BlueTeam),
        ("L01", "L-01 维护车", "SupportVehicle", U.BlueSupport),
        ("C02", "C-02 调度车", "CommandVehicle", U.RedTeam),
        ("R03", "R-03 观测平台", "ReconPlatform", U.RedTeam),
    ]
    for key, name, kind, unit in platforms:
        node(E[key], S[kind], name); g.add((E[key], S.belongsTo, unit)); g.add((unit, S.hasPlatform, E[key]))
        status = "链路降级" if turn == 1 and key in ("R02", "G02") else "维护中" if turn == 2 and key == "G02" else "就绪"
        g.add((E[key], S.status, Literal(status)))
    g.add((E.C01, S.commands, U.BlueTeam)); g.add((E.C02, S.commands, U.RedTeam)); g.add((E.L01, S.supports, U.BlueTeam))
    node(M.Observe, S.Mission, "场域观测任务"); node(M.Coordinate, S.Mission, "编组协同任务"); node(M.Support, S.Mission, "装备维护任务")
    for mission in (M.Observe, M.Coordinate, M.Support):
        g.add((mission, S.progress, Literal(TURNS[turn]["progress"], datatype=XSD.integer)))
        g.add((mission, S.status, Literal("已完成" if turn == 3 else "进行中")))
    g.add((U.BlueTeam, S.assignedTo, M.Observe)); g.add((U.BlueTeam, S.assignedTo, M.Coordinate)); g.add((U.BlueSupport, S.assignedTo, M.Support))
    g.add((E.R01, S.observes, M.Observe)); g.add((E.R02, S.observes, M.Observe))
    for i in range(turn + 1):
        node(T[f"T{i}"], S.ExerciseTurn, f"回合 {i} · {TURNS[i]['time']}")
        g.add((T[f"T{i}"], S.time, Literal(TURNS[i]["time"])))
        node(V[f"E{i}"], S.Event, TURNS[i]["title"])
        g.add((V[f"E{i}"], S.note, Literal(TURNS[i]["description"]))); g.add((V[f"E{i}"], S.occurredIn, T[f"T{i}"]))
        g.add((V[f"E{i}"], S.affects, E.R02 if i in (1, 2) else U.BlueTeam))
    for key, name, score in (("Readiness", "装备就绪率", TURNS[turn]["readiness"]), ("Coordination", "体系协同度", TURNS[turn]["coordination"])):
        node(A[key], S.Assessment, name); g.add((A[key], S.score, Literal(score, datatype=XSD.integer)))
        g.add((A[key], S.evaluates, U.BlueTeam)); g.add((A[key], S.derivedFrom, V[f"E{turn}"]))
    return g


SHAPES = '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ql: <https://example.org/qinglan/schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ql:PlatformShape a sh:NodeShape ; sh:targetClass ql:Platform ;
 sh:property [ sh:path ql:status ; sh:minCount 1 ; sh:datatype xsd:string ; sh:message "装备必须声明当前运行状态" ] .
ql:MissionShape a sh:NodeShape ; sh:targetClass ql:Mission ;
 sh:property [ sh:path ql:progress ; sh:minCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ; sh:maxInclusive 100 ; sh:message "任务进度必须为 0–100 的整数" ] .
ql:AssessmentShape a sh:NodeShape ; sh:targetClass ql:Assessment ;
 sh:property [ sh:path ql:derivedFrom ; sh:minCount 1 ; sh:message "评估结果必须能追溯至推演事件" ] .'''


def demo_payload(turn=0):
    graph = make_graph(turn)
    return {"id": DEMO_ID, "name": DEMO_NAME, "fictional": True, "turn": turn, "turns": TURNS,
        "turtle": graph.serialize(format="turtle"), "shapes": SHAPES, "namespaces": NAMESPACES,
        "triple_count": len(graph), "platforms": 8, "mission_count": 3,
        "summary": "装备—编组—任务—事件—评估。切换回合查看状态变化，运行推理查看就绪装备、编配关系和评估依据。"}
