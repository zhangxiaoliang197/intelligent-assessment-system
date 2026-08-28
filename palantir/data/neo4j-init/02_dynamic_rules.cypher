// AEGIS Dynamic Ontology metadata + deterministic derivation rules
// This file documents/deploys the same rules used by DynamicOntologyRepository.
// It does NOT pre-create DerivedEvent instances; those grow only when the engine executes.

CREATE CONSTRAINT dynamic_event_id IF NOT EXISTS FOR (n:DerivedEvent) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ontology_rule_id IF NOT EXISTS FOR (n:OntologyRule) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ontology_mutation_id IF NOT EXISTS FOR (n:OntologyMutation) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ontology_proposal_id IF NOT EXISTS FOR (n:OntologyProposal) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ontology_class_name IF NOT EXISTS FOR (n:OntologyClass) REQUIRE n.name IS UNIQUE;

UNWIND [
  {id:'RULE-TARGET-ACQUISITION-001', name:'持续目标捕获派生', outputType:'TargetAcquisitionEvent', priority:100,
   description:'侦察行动锁定机动目标并形成持续跟踪数据后，动态派生持续目标捕获事件。'},
  {id:'RULE-HIGH-VALUE-TARGET-002', name:'高价值目标研判派生', outputType:'HighValueTargetAssessment', priority:90,
   description:'目标身份被确认且被判定为最高价值打击目标后，动态派生高价值目标研判。'},
  {id:'RULE-FIRE-MISSION-READY-003', name:'火力任务就绪派生', outputType:'FireMissionReadyEvent', priority:80,
   description:'参数装订、弹药装填、阵地校准等战前准备完成后，动态派生火力任务就绪事件。'},
  {id:'RULE-BATTLE-DAMAGE-004', name:'毁伤确认派生', outputType:'BattleDamageAssessment', priority:70,
   description:'评估行动核验目标完全损毁且无残余作战能力后，动态派生毁伤确认事件。'},
  {id:'RULE-MISSION-CLOSURE-005', name:'任务闭环派生', outputType:'MissionClosureEvent', priority:60,
   description:'评估反馈被指挥单元确认且任务全额达成后，动态派生任务闭环事件。'}
] AS row
MERGE (r:OntologyRule {id:row.id})
SET r.name=row.name, r.outputType=row.outputType, r.priority=row.priority,
    r.description=row.description, r.enabled=true, r.updatedAt=datetime();

// ─────────────────────────────────────────────────────────────
// Rule example 1: dynamic "growth"
// The engine uses a unique runId so repeated cycles are idempotent.
// ─────────────────────────────────────────────────────────────
:param dataset => 'military-causal-v5';
:param runId => 'manual-preview';
:param ruleId => 'RULE-TARGET-ACQUISITION-001';

MATCH (a:ActionNode {dataset:$dataset})-[:TARGETS]->(target:Entity {dataset:$dataset})
WHERE a.name CONTAINS '锁定机动目标' OR a.directResult CONTAINS '成功锁定机动目标'
MERGE (e:DerivedEvent {id:'DERIVED-ACQUIRE-' + target.id})
ON CREATE SET e.name='持续目标捕获事件', e.eventType='TargetAcquisitionEvent',
              e.origin='RULE', e.ruleId=$ruleId, e.confidence=0.97,
              e.lifecycleStatus='ACTIVE', e.dataset=$dataset, e.createdAt=datetime(),
              e.derivationExplanation='根据底层行动事实“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，目标“' + target.name + '”满足持续目标捕获规则，因此派生该高阶事件。',
              e.evidenceNodeIds=[a.id,target.id]
WITH a,target,e
MATCH (rule:OntologyRule {id:$ruleId})
MERGE (rule)-[:PRODUCES]->(e)
MERGE (e)-[:DERIVED_FROM]->(a)
MERGE (e)-[:ABOUT]->(target);

// ─────────────────────────────────────────────────────────────
// Entity resolution candidate scan
// Exact identity evidence is deliberately conservative.
// ─────────────────────────────────────────────────────────────
MATCH (a:Entity {dataset:$dataset}), (b:Entity {dataset:$dataset})
WHERE a.id < b.id
  AND coalesce(a.lifecycleStatus,'ACTIVE')='ACTIVE'
  AND coalesce(b.lifecycleStatus,'ACTIVE')='ACTIVE'
  AND (
        (a.canonicalKey IS NOT NULL AND a.canonicalKey=b.canonicalKey)
     OR (a.sourceFingerprint IS NOT NULL AND a.sourceFingerprint=b.sourceFingerprint)
     OR toLower(replace(a.name,' ','')) = toLower(replace(b.name,' ',''))
  )
RETURN a.id,a.name,b.id,b.name,
       CASE WHEN a.canonicalKey=b.canonicalKey THEN 0.99 ELSE 0.93 END AS confidence;

// Physical disappearance / merge is NOT executed automatically here.
// DynamicOntologyController requires explicit analyst confirmation before invoking:
// CALL apoc.refactor.mergeNodes([target, source], {
//   properties:'discard', mergeRels:true, produceSelfRel:false, preserveExistingSelfRels:false
// }) YIELD node RETURN node;
