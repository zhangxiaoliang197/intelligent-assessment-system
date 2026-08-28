using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Neo4j.Driver;
using System.Text.Json;

namespace Aegis.Infrastructure.Neo4j;

public sealed class DynamicOntologyRepository : IDynamicOntologyRepository, IAsyncDisposable
{
    private const string DatasetId = MilitaryDataset.DefaultDatasetId;
    private readonly IDriver _driver;
    private readonly ILogger<DynamicOntologyRepository> _logger;

    private sealed record RuleDefinition(string Id, string Name, string Description, string OutputType, int Priority, string Cypher);

    private static readonly RuleDefinition[] Rules =
    [
        new(
            "RULE-TARGET-ACQUISITION-001",
            "持续目标捕获派生",
            "当侦察行动明确锁定机动目标并形成持续跟踪数据时，派生 TargetAcquisitionEvent。",
            "TargetAcquisitionEvent",
            100,
            """
            MATCH (a:ActionNode {dataset: $dataset})-[:TARGETS]->(target:Entity {dataset: $dataset})
            WHERE (a.name CONTAINS '锁定机动目标' OR a.directResult CONTAINS '成功锁定机动目标')
            WITH a, target
            MERGE (e:DerivedEvent {id: 'DERIVED-ACQUIRE-' + target.id})
            ON CREATE SET e.name = '持续目标捕获事件', e.eventType = 'TargetAcquisitionEvent',
                          e.origin = 'RULE', e.ruleId = $ruleId, e.confidence = 0.97,
                          e.lifecycleStatus = 'ACTIVE', e.dataset = $dataset,
                          e.createdAt = datetime(), e._createdRunId = $runId,
                          e.derivationExplanation = '根据底层行动事实“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，目标“' + target.name + '”满足规则“持续目标捕获派生”，因此派生“持续目标捕获事件”。',
                          e.evidenceNodeIds = [a.id, target.id]
            WITH e, a, target
            MATCH (rule:OntologyRule {id: $ruleId})
            MERGE (rule)-[:PRODUCES]->(e)
            MERGE (e)-[:DERIVED_FROM]->(a)
            MERGE (e)-[:ABOUT]->(target)
            WITH e, a, target WHERE e._createdRunId = $runId
            MERGE (m:OntologyMutation {id: 'MUT-' + $runId + '-' + $ruleId})
            SET m.mutationType = 'NODE_CREATED', m.executedAt = datetime(), m.ruleId = $ruleId,
                m.reason = '侦察数据满足持续目标捕获规则', m.confidence = e.confidence,
                m.sourceNodeIds = [a.id, target.id], m.targetNodeId = e.id, m.dataset = $dataset
            REMOVE e._createdRunId
            RETURN e.id AS targetId, e.name AS targetName, e.confidence AS confidence,
                   m.id AS mutationId, m.reason AS reason, [a.id, target.id] AS sourceIds
            """),
        new(
            "RULE-HIGH-VALUE-TARGET-002",
            "高价值目标研判派生",
            "当指挥研判明确确认目标身份并判定最高打击优先级时，派生 HighValueTargetAssessment。",
            "HighValueTargetAssessment",
            90,
            """
            MATCH (a:ActionNode {dataset: $dataset})-[:TARGETS]->(target:Entity {dataset: $dataset})
            WHERE a.directResult CONTAINS '最高价值打击目标'
            WITH a, target
            MERGE (e:DerivedEvent {id: 'DERIVED-HVT-' + target.id})
            ON CREATE SET e.name = '高价值目标研判', e.eventType = 'HighValueTargetAssessment',
                          e.origin = 'RULE', e.ruleId = $ruleId, e.confidence = 1.0,
                          e.lifecycleStatus = 'ACTIVE', e.dataset = $dataset,
                          e.createdAt = datetime(), e._createdRunId = $runId,
                          e.derivationExplanation = '根据底层研判事实“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，目标“' + target.name + '”已被确认身份并判定为最高价值打击目标，满足规则“高价值目标研判派生”，因此派生“高价值目标研判”。',
                          e.evidenceNodeIds = [a.id, target.id]
            WITH e, a, target
            MATCH (rule:OntologyRule {id: $ruleId})
            MERGE (rule)-[:PRODUCES]->(e)
            MERGE (e)-[:DERIVED_FROM]->(a)
            MERGE (e)-[:ABOUT]->(target)
            WITH e, a, target WHERE e._createdRunId = $runId
            MERGE (m:OntologyMutation {id: 'MUT-' + $runId + '-' + $ruleId})
            SET m.mutationType = 'NODE_CREATED', m.executedAt = datetime(), m.ruleId = $ruleId,
                m.reason = '多源研判确认目标身份与最高打击优先级', m.confidence = e.confidence,
                m.sourceNodeIds = [a.id, target.id], m.targetNodeId = e.id, m.dataset = $dataset
            REMOVE e._createdRunId
            RETURN e.id AS targetId, e.name AS targetName, e.confidence AS confidence,
                   m.id AS mutationId, m.reason AS reason, [a.id, target.id] AS sourceIds
            """),
        new(
            "RULE-FIRE-MISSION-READY-003",
            "火力任务就绪派生",
            "当火力单元完成参数装订、弹药装填与阵地校准时，派生 FireMissionReadyEvent。",
            "FireMissionReadyEvent",
            80,
            """
            MATCH (actor:Entity {dataset: $dataset})-[:PERFORMS]->(a:ActionNode {dataset: $dataset})
            WHERE a.directResult CONTAINS '战前筹备全部完成' OR a.name CONTAINS '参数装订'
            WITH a, collect(DISTINCT actor) AS actors
            MERGE (e:DerivedEvent {id: 'DERIVED-FIRE-READY-' + a.id})
            ON CREATE SET e.name = '火力任务就绪', e.eventType = 'FireMissionReadyEvent',
                          e.origin = 'RULE', e.ruleId = $ruleId, e.confidence = 0.99,
                          e.lifecycleStatus = 'ACTIVE', e.dataset = $dataset,
                          e.createdAt = datetime(), e._createdRunId = $runId,
                          e.derivationExplanation = '根据火力准备行动“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，相关火力实体已完成参数装订、弹药装填与阵地校准，满足规则“火力任务就绪派生”，因此派生“火力任务就绪”。',
                          e.evidenceNodeIds = [a.id] + [x IN actors | x.id]
            WITH e, a, actors
            MATCH (rule:OntologyRule {id: $ruleId})
            MERGE (rule)-[:PRODUCES]->(e)
            MERGE (e)-[:DERIVED_FROM]->(a)
            FOREACH (actor IN actors | MERGE (actor)-[:HAS_DERIVED_EVENT]->(e))
            WITH e, a, actors WHERE e._createdRunId = $runId
            MERGE (m:OntologyMutation {id: 'MUT-' + $runId + '-' + $ruleId})
            SET m.mutationType = 'NODE_CREATED', m.executedAt = datetime(), m.ruleId = $ruleId,
                m.reason = '火力单元满足战前准备完成规则', m.confidence = e.confidence,
                m.sourceNodeIds = [a.id] + [x IN actors | x.id], m.targetNodeId = e.id, m.dataset = $dataset
            REMOVE e._createdRunId
            RETURN e.id AS targetId, e.name AS targetName, e.confidence AS confidence,
                   m.id AS mutationId, m.reason AS reason, [a.id] + [x IN actors | x.id] AS sourceIds
            """),
        new(
            "RULE-BATTLE-DAMAGE-004",
            "毁伤确认派生",
            "当评估行动核验目标完全损毁且无残余作战能力时，派生 BattleDamageAssessment。",
            "BattleDamageAssessment",
            70,
            """
            MATCH (a:ActionNode {dataset: $dataset})-[:TARGETS]->(target:Entity {dataset: $dataset})
            WHERE a.directResult CONTAINS '核验目标完全损毁' OR a.name CONTAINS '核查目标损毁状态'
            WITH a, target
            MERGE (e:DerivedEvent {id: 'DERIVED-BDA-' + target.id})
            ON CREATE SET e.name = '毁伤确认事件', e.eventType = 'BattleDamageAssessment',
                          e.origin = 'RULE', e.ruleId = $ruleId, e.confidence = 0.99,
                          e.lifecycleStatus = 'ACTIVE', e.dataset = $dataset,
                          e.createdAt = datetime(), e._createdRunId = $runId,
                          e.derivationExplanation = '根据评估行动“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，目标“' + target.name + '”被核验为完全损毁且无残余作战能力，满足规则“毁伤确认派生”，因此派生“毁伤确认事件”。',
                          e.evidenceNodeIds = [a.id, target.id]
            WITH e, a, target
            MATCH (rule:OntologyRule {id: $ruleId})
            MERGE (rule)-[:PRODUCES]->(e)
            MERGE (e)-[:DERIVED_FROM]->(a)
            MERGE (e)-[:ABOUT]->(target)
            WITH e, a, target WHERE e._createdRunId = $runId
            MERGE (m:OntologyMutation {id: 'MUT-' + $runId + '-' + $ruleId})
            SET m.mutationType = 'NODE_CREATED', m.executedAt = datetime(), m.ruleId = $ruleId,
                m.reason = '评估数据满足目标完全毁伤确认规则', m.confidence = e.confidence,
                m.sourceNodeIds = [a.id, target.id], m.targetNodeId = e.id, m.dataset = $dataset
            REMOVE e._createdRunId
            RETURN e.id AS targetId, e.name AS targetName, e.confidence AS confidence,
                   m.id AS mutationId, m.reason AS reason, [a.id, target.id] AS sourceIds
            """),
        new(
            "RULE-MISSION-CLOSURE-005",
            "任务闭环派生",
            "当指挥单元接收评估数据并确认任务全额达成时，派生 MissionClosureEvent。",
            "MissionClosureEvent",
            60,
            """
            MATCH (actor:Entity {dataset: $dataset})-[:PERFORMS]->(a:ActionNode {dataset: $dataset})
            WHERE a.directResult CONTAINS '确认打击任务全额达成'
            WITH a, collect(DISTINCT actor) AS actors
            MERGE (e:DerivedEvent {id: 'DERIVED-MISSION-CLOSURE-' + a.id})
            ON CREATE SET e.name = '作战任务闭环', e.eventType = 'MissionClosureEvent',
                          e.origin = 'RULE', e.ruleId = $ruleId, e.confidence = 1.0,
                          e.lifecycleStatus = 'ACTIVE', e.dataset = $dataset,
                          e.createdAt = datetime(), e._createdRunId = $runId,
                          e.derivationExplanation = '根据指挥闭环行动“' + a.name + '”及其直接结果“' + coalesce(a.directResult,'') + '”，评估反馈已被接收且任务被确认全额达成，满足规则“任务闭环派生”，因此派生“作战任务闭环”。',
                          e.evidenceNodeIds = [a.id] + [x IN actors | x.id]
            WITH e, a, actors
            MATCH (rule:OntologyRule {id: $ruleId})
            MERGE (rule)-[:PRODUCES]->(e)
            MERGE (e)-[:DERIVED_FROM]->(a)
            FOREACH (actor IN actors | MERGE (actor)-[:HAS_DERIVED_EVENT]->(e))
            WITH e, a, actors WHERE e._createdRunId = $runId
            MERGE (m:OntologyMutation {id: 'MUT-' + $runId + '-' + $ruleId})
            SET m.mutationType = 'NODE_CREATED', m.executedAt = datetime(), m.ruleId = $ruleId,
                m.reason = '评估反馈与任务完成条件共同满足闭环规则', m.confidence = e.confidence,
                m.sourceNodeIds = [a.id] + [x IN actors | x.id], m.targetNodeId = e.id, m.dataset = $dataset
            REMOVE e._createdRunId
            RETURN e.id AS targetId, e.name AS targetName, e.confidence AS confidence,
                   m.id AS mutationId, m.reason AS reason, [a.id] + [x IN actors | x.id] AS sourceIds
            """)
    ];

    public DynamicOntologyRepository(IConfiguration configuration, ILogger<DynamicOntologyRepository> logger)
    {
        _logger = logger;
        var uri = configuration["ConnectionStrings:Neo4j"] ?? "bolt://localhost:7687";
        var user = configuration["Neo4j:User"] ?? "neo4j";
        var password = configuration["Neo4j:Password"] ?? "aegis2026!";
        _driver = GraphDatabase.Driver(uri, AuthTokens.Basic(user, password));
    }

    public async Task EnsureSchemaAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        foreach (var statement in new[]
        {
            "CREATE CONSTRAINT dynamic_event_id IF NOT EXISTS FOR (n:DerivedEvent) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT ontology_rule_id IF NOT EXISTS FOR (n:OntologyRule) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT ontology_mutation_id IF NOT EXISTS FOR (n:OntologyMutation) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT ontology_proposal_id IF NOT EXISTS FOR (n:OntologyProposal) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT ontology_class_name IF NOT EXISTS FOR (n:OntologyClass) REQUIRE n.name IS UNIQUE"
        })
        {
            await (await session.RunAsync(statement)).ConsumeAsync();
        }

        await (await session.RunAsync(
            """
            UNWIND $rules AS row
            MERGE (r:OntologyRule {id: row.id})
            SET r.name = row.name, r.description = row.description, r.outputType = row.outputType,
                r.enabled = true, r.priority = row.priority, r.updatedAt = datetime()
            """,
            new
            {
                rules = Rules.Select(r => new { id = r.Id, name = r.Name, description = r.Description, outputType = r.OutputType, priority = r.Priority }).ToArray()
            })).ConsumeAsync();
    }

    public async Task<CausalGraphResult> GetDynamicGraphAsync(CancellationToken cancellationToken = default)
    {
        await EnsureSchemaAsync(cancellationToken);
        await using var session = _driver.AsyncSession();
        var nodes = new List<CausalGraphNode>();
        var edges = new List<CausalGraphEdge>();
        var nodeIds = new HashSet<string>();

        var nodeResult = await session.RunAsync(
            """
            MATCH (n)
            WHERE (n.dataset = $dataset AND (n:Entity OR n:ActionNode OR n:DerivedEvent))
               OR n:OntologyRule OR n:OntologyClass OR n:OntologyRelationType OR (n:OntologyProposal AND n.status IN ['PROPOSED','APPROVED'])
            RETURN n,
                   CASE
                     WHEN n:DerivedEvent THEN 'DerivedEvent'
                     WHEN n:OntologyRule THEN 'OntologyRule'
                     WHEN n:OntologyProposal THEN 'OntologyProposal'
                     WHEN n:OntologyClass THEN 'OntologyClass'
                     WHEN n:OntologyRelationType THEN 'OntologyRelationType'
                     WHEN n:ActionNode THEN 'ActionNode'
                     ELSE 'Entity'
                   END AS nodeType
            ORDER BY nodeType, coalesce(n.sequence, 0), coalesce(n.name, n.id)
            """,
            new { dataset = DatasetId });

        await nodeResult.ForEachAsync(record =>
        {
            var node = record["n"].As<INode>();
            var type = record["nodeType"].As<string>();
            var id = NodeId(node);
            if (!nodeIds.Add(id)) return;
            var properties = node.Properties.ToDictionary(k => k.Key, v => (object?)v.Value);
            nodes.Add(new CausalGraphNode
            {
                Id = id,
                Label = properties.TryGetValue("name", out var name) ? name?.ToString() ?? id : id,
                Type = type,
                Category = type == "Entity" ? properties.GetValueOrDefault("ontologyType")?.ToString() : properties.GetValueOrDefault("eventType")?.ToString() ?? type,
                Role = properties.GetValueOrDefault("operationalRole")?.ToString() ?? (type == "DerivedEvent" ? "derived" : type == "OntologyProposal" ? "proposal" : type == "OntologyRule" ? "rule" : "action"),
                Properties = properties
            });
        });

        var edgeResult = await session.RunAsync(
            """
            MATCH (a)-[r]->(b)
            WHERE a.id IS NOT NULL AND b.id IS NOT NULL
              AND (
                   (a.dataset = $dataset AND b.dataset = $dataset)
                   OR a:OntologyRule OR b:OntologyRule
                   OR a:OntologyProposal OR b:OntologyProposal OR a:OntologyClass OR b:OntologyClass OR a:OntologyRelationType OR b:OntologyRelationType
              )
              AND type(r) IN ['OPERATES','PERFORMS','TARGETS','DIRECTED_TO','CAUSES','DERIVED_FROM','ABOUT','HAS_DERIVED_EVENT','PRODUCES','POSSIBLY_SAME_AS','SAME_AS','RELATED_TO','PROPOSES_CLASS','PROPOSES_RELATION','PROPOSES_RULE']
            RETURN a.id AS source, b.id AS target, type(r) AS relType, properties(r) AS props
            """,
            new { dataset = DatasetId });
        await edgeResult.ForEachAsync(record =>
        {
            var source = record["source"].As<string>();
            var target = record["target"].As<string>();
            if (!nodeIds.Contains(source) || !nodeIds.Contains(target)) return;
            var relType = record["relType"].As<string>();
            var props = record["props"].As<IDictionary<string, object>>().ToDictionary(k => k.Key, v => (object?)v.Value);
            edges.Add(new CausalGraphEdge
            {
                Id = $"{source}:{relType}:{target}",
                Source = source,
                Target = target,
                Type = relType,
                Properties = props
            });
        });

        return new CausalGraphResult { Nodes = nodes, Edges = edges };
    }

    public Task<IReadOnlyList<OntologyRuleDescriptor>> GetRulesAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<OntologyRuleDescriptor>>(Rules.Select(r => new OntologyRuleDescriptor(r.Id, r.Name, r.Description, r.OutputType, true, r.Priority)).ToArray());

    public async Task<DynamicOntologyRunResult> RunDerivationRulesAsync(CancellationToken cancellationToken = default)
    {
        await EnsureSchemaAsync(cancellationToken);
        var runId = Guid.NewGuid().ToString("N");
        var mutations = new List<OntologyMutation>();
        await using var session = _driver.AsyncSession();

        foreach (var rule in Rules.OrderByDescending(r => r.Priority))
        {
            try
            {
                var result = await session.RunAsync(rule.Cypher, new { dataset = DatasetId, ruleId = rule.Id, runId });
                await result.ForEachAsync(record =>
                {
                    var mutation = new OntologyMutation(
                        record["mutationId"].As<string>(),
                        OntologyMutationTypes.NodeCreated,
                        DateTimeOffset.UtcNow,
                        rule.Id,
                        record["reason"].As<string?>(),
                        record["confidence"].As<double>(),
                        record["sourceIds"].As<List<string>>(),
                        record["targetId"].As<string>(),
                        new Dictionary<string, object?> { ["targetName"] = record["targetName"].As<string>() });
                    mutations.Add(mutation);
                });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Dynamic ontology rule {RuleId} failed", rule.Id);
            }
        }

        return new DynamicOntologyRunResult(mutations.Count, mutations.Count, mutations);
    }

    public async Task<IReadOnlyList<ResolutionCandidate>> FindResolutionCandidatesAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(
            """
            MATCH (a:Entity {dataset: $dataset}), (b:Entity {dataset: $dataset})
            WHERE a.id < b.id
              AND coalesce(a.lifecycleStatus, 'ACTIVE') = 'ACTIVE'
              AND coalesce(b.lifecycleStatus, 'ACTIVE') = 'ACTIVE'
              AND (
                    (a.canonicalKey IS NOT NULL AND a.canonicalKey = b.canonicalKey)
                 OR (a.sourceFingerprint IS NOT NULL AND a.sourceFingerprint = b.sourceFingerprint)
                 OR (toLower(replace(a.name, ' ', '')) = toLower(replace(b.name, ' ', '')))
              )
            RETURN a.id AS leftId, a.name AS leftName, b.id AS rightId, b.name AS rightName,
                   CASE
                     WHEN a.canonicalKey IS NOT NULL AND a.canonicalKey = b.canonicalKey THEN 0.99
                     WHEN a.sourceFingerprint IS NOT NULL AND a.sourceFingerprint = b.sourceFingerprint THEN 0.98
                     ELSE 0.93
                   END AS confidence,
                   CASE
                     WHEN a.canonicalKey IS NOT NULL AND a.canonicalKey = b.canonicalKey THEN 'canonicalKey一致'
                     WHEN a.sourceFingerprint IS NOT NULL AND a.sourceFingerprint = b.sourceFingerprint THEN 'sourceFingerprint一致'
                     ELSE '归一化名称一致'
                   END AS basis
            ORDER BY confidence DESC
            LIMIT 50
            """,
            new { dataset = DatasetId });
        var rows = new List<ResolutionCandidate>();
        await result.ForEachAsync(record => rows.Add(new ResolutionCandidate(
            record["leftId"].As<string>(), record["leftName"].As<string>(),
            record["rightId"].As<string>(), record["rightName"].As<string>(),
            record["confidence"].As<double>(), record["basis"].As<string>(),
            record["confidence"].As<double>() >= 0.98 ? "建议人工确认后物理融合" : "建议建立 POSSIBLY_SAME_AS，暂不物理融合")));
        return rows;
    }

    public async Task<OntologyMutation> MergeNodesAsync(MergeNodesRequest request, CancellationToken cancellationToken = default)
    {
        if (request.SourceNodeId == request.TargetNodeId) throw new ArgumentException("Source and target cannot be the same node.");
        await EnsureSchemaAsync(cancellationToken);
        await using var session = _driver.AsyncSession();
        var mutationId = $"MUT-MERGE-{Guid.NewGuid():N}";

        if (!request.PhysicalMerge)
        {
            var result = await session.RunAsync(
                """
                MATCH (source:Entity {id: $sourceId}), (target:Entity {id: $targetId})
                MERGE (source)-[r:POSSIBLY_SAME_AS]->(target)
                SET r.confidence = $confidence, r.reason = $reason, r.createdAt = datetime()
                MERGE (m:OntologyMutation {id: $mutationId})
                SET m.mutationType = 'RELATION_CREATED', m.executedAt = datetime(), m.reason = $reason,
                    m.confidence = $confidence, m.sourceNodeIds = [$sourceId, $targetId], m.targetNodeId = $targetId,
                    m.dataset = $dataset
                RETURN source.name AS sourceName, target.name AS targetName
                """,
                new { sourceId = request.SourceNodeId, targetId = request.TargetNodeId, confidence = request.Confidence, reason = request.Reason, mutationId, dataset = DatasetId });
            await result.ConsumeAsync();
            return new OntologyMutation(mutationId, OntologyMutationTypes.RelationCreated, DateTimeOffset.UtcNow, null, request.Reason, request.Confidence, [request.SourceNodeId, request.TargetNodeId], request.TargetNodeId, new Dictionary<string, object?> { ["mode"] = "POSSIBLY_SAME_AS" });
        }

        // Persist an immutable audit record BEFORE the destructive APOC merge.
        await (await session.RunAsync(
            """
            MATCH (source:Entity {id: $sourceId}), (target:Entity {id: $targetId})
            MERGE (m:OntologyMutation {id: $mutationId})
            SET m.mutationType = 'NODE_MERGED', m.executedAt = datetime(), m.reason = $reason,
                m.confidence = $confidence, m.sourceNodeIds = [$sourceId, $targetId], m.targetNodeId = $targetId,
                m.sourceSnapshot = apoc.convert.toJson(properties(source)), m.targetSnapshot = apoc.convert.toJson(properties(target)), m.dataset = $dataset
            """,
            new { sourceId = request.SourceNodeId, targetId = request.TargetNodeId, confidence = request.Confidence, reason = request.Reason, mutationId, dataset = DatasetId })).ConsumeAsync();

        // The target node is deliberately placed FIRST; APOC + properties:'discard' keeps the canonical target values on conflicts.
        var mergeResult = await session.RunAsync(
            """
            MATCH (source:Entity {id: $sourceId}), (target:Entity {id: $targetId})
            CALL apoc.refactor.mergeNodes([target, source], {properties:'discard', mergeRels:true, produceSelfRel:false, preserveExistingSelfRels:false})
            YIELD node
            SET node.id = $targetId, node.lifecycleStatus = 'ACTIVE', node.lastResolvedAt = datetime()
            RETURN node.id AS id, node.name AS name
            """,
            new { sourceId = request.SourceNodeId, targetId = request.TargetNodeId });
        await mergeResult.ConsumeAsync();

        return new OntologyMutation(mutationId, OntologyMutationTypes.NodeMerged, DateTimeOffset.UtcNow, null, request.Reason, request.Confidence, [request.SourceNodeId, request.TargetNodeId], request.TargetNodeId, new Dictionary<string, object?> { ["physicalMerge"] = true });
    }

    public async Task<IReadOnlyList<OntologyMutation>> GetMutationsAsync(int limit = 50, CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var safeLimit = Math.Clamp(limit, 1, 200);
        var result = await session.RunAsync($"""
            MATCH (m:OntologyMutation)
            WHERE m.dataset = $dataset
            RETURN m ORDER BY m.executedAt DESC LIMIT {safeLimit}
            """, new { dataset = DatasetId });
        var mutations = new List<OntologyMutation>();
        await result.ForEachAsync(record =>
        {
            var node = record["m"].As<INode>();
            var p = node.Properties;
            mutations.Add(new OntologyMutation(
                p["id"].As<string>(),
                p.GetValueOrDefault("mutationType")?.As<string>() ?? "UNKNOWN",
                ToDateTimeOffset(p.GetValueOrDefault("executedAt")),
                p.GetValueOrDefault("ruleId")?.As<string?>(),
                p.GetValueOrDefault("reason")?.As<string?>(),
                p.GetValueOrDefault("confidence")?.As<double?>() ?? 0,
                p.GetValueOrDefault("sourceNodeIds")?.As<List<string>>() ?? [],
                p.GetValueOrDefault("targetNodeId")?.As<string?>(),
                p.Where(x => x.Key is not ("id" or "mutationType" or "executedAt" or "ruleId" or "reason" or "confidence" or "sourceNodeIds" or "targetNodeId"))
                    .ToDictionary(x => x.Key, x => (object?)x.Value)));
        });
        return mutations;
    }

    public async Task<DynamicOntologyStatistics> GetStatisticsAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(
            """
            CALL { MATCH (n {dataset: $dataset}) WHERE n:Entity OR n:ActionNode OR n:StateNode RETURN count(n) AS asserted }
            CALL { MATCH (n:DerivedEvent {dataset: $dataset}) RETURN count(n) AS derived }
            CALL { MATCH (n {dataset: $dataset}) WHERE (n:Entity OR n:ActionNode OR n:DerivedEvent) AND coalesce(n.lifecycleStatus,'ACTIVE')='ACTIVE' RETURN count(n) AS active }
            CALL { MATCH (r:OntologyRule) WHERE coalesce(r.enabled,true) RETURN count(r) AS rules }
            CALL { MATCH (a:Entity {dataset: $dataset}), (b:Entity {dataset: $dataset}) WHERE a.id < b.id AND coalesce(a.lifecycleStatus,'ACTIVE')='ACTIVE' AND coalesce(b.lifecycleStatus,'ACTIVE')='ACTIVE' AND ((a.canonicalKey IS NOT NULL AND a.canonicalKey=b.canonicalKey) OR (a.sourceFingerprint IS NOT NULL AND a.sourceFingerprint=b.sourceFingerprint) OR toLower(replace(a.name,' ',''))=toLower(replace(b.name,' ',''))) RETURN count(*) AS resolution }
            CALL { MATCH (p:OntologyProposal {status:'PROPOSED', dataset:$dataset}) RETURN count(p) AS proposals }
            CALL { MATCH (m:OntologyMutation {dataset:$dataset}) RETURN count(m) AS mutations }
            RETURN asserted, derived, active, rules, resolution, proposals, mutations
            """,
            new { dataset = DatasetId });
        var row = await result.SingleAsync();
        return new DynamicOntologyStatistics(
            (int)row["asserted"].As<long>(), (int)row["derived"].As<long>(), (int)row["active"].As<long>(), (int)row["rules"].As<long>(),
            (int)row["resolution"].As<long>(), (int)row["proposals"].As<long>(), (int)row["mutations"].As<long>());
    }

    public async Task<ManualOntologyNodeResult> CreateManualNodeAsync(ManualOntologyNodeRequest request, CancellationToken cancellationToken = default)
    {
        var allowedTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ForceUnit", "Equipment", "Target" };
        if (!allowedTypes.Contains(request.OntologyType)) throw new ArgumentException("OntologyType must be ForceUnit, Equipment or Target.");
        var idPrefix = request.OntologyType.ToUpperInvariant();
        var id = $"{idPrefix}-MANUAL-{Guid.NewGuid().ToString("N")[..10].ToUpperInvariant()}";
        var staticProps = JsonSerializer.Serialize(request.Properties);
        var canonicalKey = string.IsNullOrWhiteSpace(request.CanonicalKey) ? NormalizeName(request.Name) : request.CanonicalKey.Trim();
        await using var session = _driver.AsyncSession();
        await (await session.RunAsync(
            """
            CREATE (e:Entity {id: $id, name: $name, ontologyType: $ontologyType,
                              operationalRole: $operationalRole, staticProps: $staticProps,
                              canonicalKey: $canonicalKey, origin: 'MANUAL', lifecycleStatus: 'ACTIVE',
                              dataset: $dataset, createdAt: datetime()})
            CREATE (m:OntologyMutation {id: $mutationId, mutationType:'NODE_CREATED', executedAt:datetime(),
                       reason:'人工新建本体实例', confidence:1.0, sourceNodeIds:[], targetNodeId:$id, dataset:$dataset})
            """,
            new { id, name = request.Name.Trim(), ontologyType = request.OntologyType, operationalRole = request.OperationalRole, staticProps, canonicalKey, dataset = DatasetId, mutationId = $"MUT-MANUAL-{Guid.NewGuid():N}" })).ConsumeAsync();
        return new ManualOntologyNodeResult(id, request.Name.Trim(), request.OntologyType);
    }

    public async Task<OntologyMutation> CreateManualRelationAsync(ManualOntologyRelationRequest request, CancellationToken cancellationToken = default)
    {
        var relation = request.RelationType.Trim().ToUpperInvariant();
        var allowed = new HashSet<string> { "OPERATES", "RELATED_TO", "SAME_AS", "POSSIBLY_SAME_AS" };
        if (!allowed.Contains(relation)) throw new ArgumentException($"Unsupported relation type: {relation}");
        var mutationId = $"MUT-REL-{Guid.NewGuid():N}";
        await using var session = _driver.AsyncSession();
        // The relation type cannot be passed as a Cypher parameter, so it is interpolated only
        // after being validated against the strict allow-list above. With two '$' characters,
        // ordinary single Cypher braces remain literal content and '{{relation}}' is the C# interpolation.
        var cypher = $$"""
            MATCH (a:Entity {id: $sourceId}), (b:Entity {id: $targetId})
            MERGE (a)-[r:{{relation}}]->(b)
            SET r.origin = 'MANUAL', r.createdAt = datetime()
            MERGE (m:OntologyMutation {id: $mutationId})
            SET m.mutationType='RELATION_CREATED', m.executedAt=datetime(), m.reason='人工创建关系',
                m.confidence=1.0, m.sourceNodeIds=[$sourceId,$targetId], m.targetNodeId=$targetId, m.dataset=$dataset
            """;
        await (await session.RunAsync(cypher, new { sourceId = request.SourceId, targetId = request.TargetId, mutationId, dataset = DatasetId })).ConsumeAsync();
        return new OntologyMutation(mutationId, OntologyMutationTypes.RelationCreated, DateTimeOffset.UtcNow, null, "人工创建关系", 1.0, [request.SourceId, request.TargetId], request.TargetId, new Dictionary<string, object?> { ["relationType"] = relation });
    }

    public async Task<OntologyAgentContext> BuildAgentContextAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(
            """
            CALL { MATCH (n) WHERE n.dataset=$dataset AND (n:Entity OR n:ActionNode OR n:DerivedEvent) RETURN collect(DISTINCT coalesce(n.ontologyType, n.eventType, labels(n)[0])) AS nodeTypes }
            CALL { MATCH ()-[r]->() RETURN collect(DISTINCT type(r)) AS relTypes }
            CALL { MATCH (e:Entity {dataset:$dataset}) RETURN collect(e.name)[0..20] AS entitySamples }
            CALL { MATCH (e:DerivedEvent {dataset:$dataset}) RETURN collect(e.name)[0..20] AS derivedSamples }
            CALL { MATCH (r:OntologyRule) RETURN collect(r.name + ': ' + r.description) AS rules }
            RETURN nodeTypes, relTypes, entitySamples, derivedSamples, rules
            """,
            new { dataset = DatasetId });
        var row = await result.SingleAsync();
        return new OntologyAgentContext(
            row["nodeTypes"].As<List<string>>(), row["relTypes"].As<List<string>>(), row["entitySamples"].As<List<string>>(),
            row["derivedSamples"].As<List<string>>(), row["rules"].As<List<string>>());
    }

    public async Task<OntologyProposal> SaveProposalAsync(OntologyProposal proposal, CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        await (await session.RunAsync(
            """
            MERGE (p:OntologyProposal {id:$id})
            SET p.proposalType=$proposalType, p.name=$name, p.parentClass=$parentClass,
                p.description=$description, p.confidence=$confidence, p.evidence=$evidence,
                p.status=$status, p.origin='AGENT', p.dataset=$dataset, p.createdAt=datetime($createdAt)
            MERGE (m:OntologyMutation {id:$mutationId})
            SET m.mutationType='PROPOSAL_CREATED', m.executedAt=datetime(), m.reason='Ontology Resolution Agent 提交本体扩充建议',
                m.confidence=$confidence, m.sourceNodeIds=[], m.targetNodeId=$id, m.dataset=$dataset
            """,
            new
            {
                id = proposal.Id, proposalType = proposal.ProposalType, name = proposal.Name, parentClass = proposal.ParentClass,
                description = proposal.Description, confidence = proposal.Confidence, evidence = proposal.Evidence.ToArray(), status = proposal.Status,
                createdAt = proposal.CreatedAt.ToString("O"), mutationId = $"MUT-PROP-{Guid.NewGuid():N}", dataset = DatasetId
            })).ConsumeAsync();
        return proposal;
    }

    public async Task<OntologyMutation> ApproveProposalAsync(string proposalId, CancellationToken cancellationToken = default)
    {
        var mutationId = $"MUT-APPROVE-{Guid.NewGuid():N}";
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(
            """
            MATCH (p:OntologyProposal {id:$proposalId})
            SET p.status='APPROVED', p.approvedAt=datetime()
            FOREACH (_ IN CASE WHEN p.proposalType='NEW_CLASS' THEN [1] ELSE [] END |
              MERGE (c:OntologyClass {name:p.name})
              SET c.id='ONTOCLASS-' + p.id, c.parentClass=p.parentClass, c.description=p.description, c.origin='AGENT', c.dataset=$dataset, c.lifecycleStatus='ACTIVE', c.createdAt=datetime(), c.evidence=p.evidence, c.sourceExplanation='根据 Ontology_Resolution_Agent 对当前图谱重复结构的分析建议，并经人工批准后加入本体；原始建议：' + p.description
              MERGE (p)-[:PROPOSES_CLASS]->(c)
            )
            FOREACH (_ IN CASE WHEN p.proposalType='NEW_RELATION' THEN [1] ELSE [] END |
              MERGE (r:OntologyRelationType {name:p.name})
              SET r.id='RELTYPE-' + p.id, r.description=p.description, r.origin='AGENT', r.dataset=$dataset, r.lifecycleStatus='ACTIVE', r.createdAt=datetime(), r.evidence=p.evidence, r.sourceExplanation='根据 Ontology_Resolution_Agent 对当前关系结构的分析建议，并经人工批准后加入本体；原始建议：' + p.description
              MERGE (p)-[:PROPOSES_RELATION]->(r)
            )
            FOREACH (_ IN CASE WHEN p.proposalType='NEW_RULE' THEN [1] ELSE [] END |
              MERGE (r:OntologyRule {id:'AGENT-RULE-' + p.id})
              SET r.name=p.name, r.description=p.description, r.outputType='AgentProposed', r.origin='AGENT', r.dataset=$dataset,
                  r.enabled=false, r.status='DRAFT_REVIEW_REQUIRED', r.priority=10, r.createdAt=datetime(), r.evidence=p.evidence, r.sourceExplanation='根据 Ontology_Resolution_Agent 对当前图谱模式的分析建议生成规则草案；该规则仍需人工复核后方可启用。原始建议：' + p.description
              MERGE (p)-[:PROPOSES_RULE]->(r)
            )
            MERGE (m:OntologyMutation {id:$mutationId})
            SET m.mutationType='PROPOSAL_APPROVED', m.executedAt=datetime(), m.reason='人工批准 Agent 本体扩充建议',
                m.confidence=p.confidence, m.sourceNodeIds=[p.id], m.targetNodeId=p.id, m.dataset=$dataset
            RETURN p.confidence AS confidence, p.name AS name
            """,
            new { proposalId, mutationId, dataset = DatasetId });
        var record = await result.SingleAsync();
        return new OntologyMutation(mutationId, OntologyMutationTypes.ProposalApproved, DateTimeOffset.UtcNow, null, "人工批准 Agent 本体扩充建议", record["confidence"].As<double>(), [proposalId], proposalId, new Dictionary<string, object?> { ["name"] = record["name"].As<string>() });
    }

    public async Task<IReadOnlyList<OntologyProposal>> GetProposalsAsync(string? status = null, CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(
            """
            MATCH (p:OntologyProposal {dataset:$dataset})
            WHERE $status IS NULL OR p.status=$status
            RETURN p ORDER BY p.createdAt DESC
            """,
            new { status, dataset = DatasetId });
        var proposals = new List<OntologyProposal>();
        await result.ForEachAsync(record =>
        {
            var p = record["p"].As<INode>().Properties;
            proposals.Add(new OntologyProposal
            {
                Id = p["id"].As<string>(), ProposalType = p["proposalType"].As<string>(), Name = p["name"].As<string>(),
                ParentClass = p.GetValueOrDefault("parentClass")?.As<string?>(), Description = p["description"].As<string>(),
                Confidence = p.GetValueOrDefault("confidence")?.As<double?>() ?? 0, Evidence = p.GetValueOrDefault("evidence")?.As<List<string>>() ?? [],
                Status = p.GetValueOrDefault("status")?.As<string>() ?? "PROPOSED", CreatedAt = ToDateTimeOffset(p.GetValueOrDefault("createdAt"))
            });
        });
        return proposals;
    }

    private static string NodeId(INode node) => node.Properties.GetValueOrDefault("id")?.As<string?>() ?? node.ElementId;
    private static string NormalizeName(string value) => string.Concat(value.Where(ch => !char.IsWhiteSpace(ch))).ToLowerInvariant();

    private static DateTimeOffset ToDateTimeOffset(object? value)
    {
        if (value is DateTimeOffset dto) return dto;
        if (value is DateTime dt) return new DateTimeOffset(dt);
        return DateTimeOffset.TryParse(value?.ToString(), out var parsed) ? parsed : DateTimeOffset.UtcNow;
    }

    public async ValueTask DisposeAsync() => await _driver.DisposeAsync();
}
