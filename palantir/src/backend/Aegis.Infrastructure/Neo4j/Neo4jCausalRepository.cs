using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Neo4j.Driver;
using System.Text.Json;

namespace Aegis.Infrastructure.Neo4j;

public sealed class Neo4jCausalRepository : ICausalRepository, IAsyncDisposable
{
    private const string DatasetId = MilitaryDataset.DefaultDatasetId;
    private readonly IDriver _driver;
    private readonly ILogger<Neo4jCausalRepository> _logger;

    public Neo4jCausalRepository(IConfiguration configuration, ILogger<Neo4jCausalRepository> logger)
    {
        _logger = logger;
        var uri = configuration["ConnectionStrings:Neo4j"] ?? "bolt://localhost:7687";
        var user = configuration["Neo4j:User"] ?? "neo4j";
        var password = configuration["Neo4j:Password"] ?? "aegis2026!";
        _driver = GraphDatabase.Driver(uri, AuthTokens.Basic(user, password));
    }

    public async Task<MilitarySeedResult> SeedMilitaryDatasetAsync(
        MilitaryDataset dataset,
        CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();

        foreach (var constraint in new[]
        {
            "CREATE CONSTRAINT aegis_entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT aegis_action_id IF NOT EXISTS FOR (n:ActionNode) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT aegis_state_id IF NOT EXISTS FOR (n:StateNode) REQUIRE n.id IS UNIQUE"
        })
        {
            await (await session.RunAsync(constraint)).ConsumeAsync();
        }

        await (await session.RunAsync(
            """
            MATCH (n)
            WHERE n.dataset STARTS WITH 'military-causal-' AND (
                n:Entity OR n:ActionNode OR n:StateNode OR n:DerivedEvent OR n:OntologyMutation OR
                n:OntologyProposal OR n:OntologyClass OR n:OntologyRelationType OR (n:OntologyRule AND n.origin = 'AGENT')
            )
            DETACH DELETE n
            """,
            new { dataset = dataset.Id })).ConsumeAsync();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MERGE (e:Entity {id: row.id})
            SET e.name = row.name,
                e.ontologyType = row.ontologyType,
                e.operationalRole = row.operationalRole,
                e.staticProps = row.staticProps,
                e.canonicalKey = row.canonicalKey,
                e.origin = 'ASSERTED',
                e.lifecycleStatus = 'ACTIVE',
                e.dataset = $dataset
            """,
            new
            {
                dataset = dataset.Id,
                rows = dataset.Entities.Select(e => new
                {
                    id = e.Id,
                    name = e.Name,
                    ontologyType = e.OntologyType,
                    operationalRole = e.OperationalRole,
                    staticProps = JsonSerializer.Serialize(e.StaticProps),
                    canonicalKey = e.Id
                }).ToArray()
            })).ConsumeAsync();

        // Static ontology relation: ForceUnit OPERATES Equipment.
        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MATCH (from:Entity {id: row.from, dataset: $dataset})
            MATCH (to:Entity {id: row.to, dataset: $dataset})
            MERGE (from)-[:OPERATES]->(to)
            """,
            new
            {
                dataset = dataset.Id,
                rows = dataset.EntityRelations
                    .Where(r => r.RelationType == "OPERATES")
                    .Select(r => new { from = r.FromEntityId, to = r.ToEntityId })
                    .ToArray()
            })).ConsumeAsync();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MERGE (a:ActionNode {id: row.id})
            SET a.name = row.name,
                a.sequence = row.sequence,
                a.timeNode = row.timeNode,
                a.timestamp = row.timestamp,
                a.location = row.location,
                a.actionType = row.actionType,
                a.actionObject = row.actionObject,
                a.directResult = row.directResult,
                a.isCausalTerminal = row.isCausalTerminal,
                a.origin = 'ASSERTED',
                a.lifecycleStatus = 'ACTIVE',
                a.dataset = $dataset
            """,
            new
            {
                dataset = dataset.Id,
                rows = dataset.Actions.Select(a => new
                {
                    id = a.Id,
                    name = a.Name,
                    sequence = a.Sequence,
                    timeNode = a.TimeNode,
                    timestamp = a.Timestamp,
                    location = a.Location,
                    actionType = a.ActionType,
                    actionObject = a.ActionObject,
                    directResult = a.DirectResult,
                    isCausalTerminal = a.IsCausalTerminal
                }).ToArray()
            })).ConsumeAsync();

        var performerRows = dataset.Actions
            .SelectMany(a => a.PerformerEntityIds.Select(entityId => new { entity = entityId, action = a.Id }))
            .ToArray();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MATCH (actor:Entity {id: row.entity, dataset: $dataset})
            MATCH (action:ActionNode {id: row.action, dataset: $dataset})
            MERGE (actor)-[:PERFORMS]->(action)
            """,
            new { dataset = dataset.Id, rows = performerRows })).ConsumeAsync();

        var targetRows = dataset.Actions
            .SelectMany(a => a.TargetEntityIds.Select(entityId => new { action = a.Id, entity = entityId }))
            .ToArray();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MATCH (action:ActionNode {id: row.action, dataset: $dataset})
            MATCH (target:Entity {id: row.entity, dataset: $dataset})
            MERGE (action)-[:TARGETS]->(target)
            """,
            new { dataset = dataset.Id, rows = targetRows })).ConsumeAsync();

        var recipientRows = dataset.Actions
            .SelectMany(a => a.RecipientEntityIds.Select(entityId => new { action = a.Id, entity = entityId }))
            .ToArray();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MATCH (action:ActionNode {id: row.action, dataset: $dataset})
            MATCH (recipient:Entity {id: row.entity, dataset: $dataset})
            MERGE (action)-[:DIRECTED_TO]->(recipient)
            """,
            new { dataset = dataset.Id, rows = recipientRows })).ConsumeAsync();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MERGE (s:StateNode {id: row.id})
            SET s.entityId = row.entityId,
                s.sequence = row.sequence,
                s.timestamp = row.timestamp,
                s.location = row.location,
                s.action = row.action,
                s.actionObject = row.actionObject,
                s.directResult = row.directResult,
                s.updatedState = row.updatedState,
                s.sourceBasis = row.sourceBasis,
                s.latitude = row.latitude,
                s.longitude = row.longitude,
                s.origin = 'ASSERTED',
                s.lifecycleStatus = 'ACTIVE',
                s.dataset = $dataset
            WITH row, s
            MATCH (e:Entity {id: row.entityId, dataset: $dataset})
            MERGE (e)-[hs:HAS_STATE]->(s)
            SET hs.time = row.timestamp,
                hs.location = row.location,
                hs.sequence = row.sequence
            """,
            new
            {
                dataset = dataset.Id,
                rows = dataset.States.Select(s => new
                {
                    id = s.Id,
                    entityId = s.EntityId,
                    sequence = s.Sequence,
                    timestamp = s.Timestamp,
                    location = s.Location,
                    action = s.Action,
                    actionObject = s.ActionObject,
                    directResult = s.DirectResult,
                    updatedState = s.UpdatedState,
                    sourceBasis = s.SourceBasis,
                    latitude = s.Latitude,
                    longitude = s.Longitude
                }).ToArray()
            })).ConsumeAsync();

        await (await session.RunAsync(
            """
            UNWIND $rows AS row
            MATCH (from:ActionNode {id: row.from, dataset: $dataset})
            MATCH (to:ActionNode {id: row.to, dataset: $dataset})
            MERGE (from)-[:CAUSES]->(to)
            """,
            new
            {
                dataset = dataset.Id,
                rows = dataset.Causes.Select(c => new { from = c.FromActionId, to = c.ToActionId }).ToArray()
            })).ConsumeAsync();

        var relationshipCount = dataset.EntityRelations.Count
            + performerRows.Length
            + targetRows.Length
            + recipientRows.Length
            + dataset.Causes.Count
            + dataset.States.Count;

        _logger.LogInformation(
            "Seeded ontology-normalized dataset {Dataset}: {Entities} entities, {Actions} actions, {States} states, {Relationships} relationships",
            dataset.Id,
            dataset.Entities.Count,
            dataset.Actions.Count,
            dataset.States.Count,
            relationshipCount);

        return new MilitarySeedResult(
            dataset.Id,
            dataset.Entities.Count,
            dataset.Actions.Count,
            dataset.States.Count,
            relationshipCount);
    }

    public async Task<CausalGraphResult> GetOverviewAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var nodes = new Dictionary<string, CausalGraphNode>(StringComparer.Ordinal);
        var edges = new List<CausalGraphEdge>();

        var nodeCursor = await session.RunAsync(
            """
            MATCH (n)
            WHERE n.dataset = $dataset AND (n:Entity OR n:ActionNode)
            RETURN n, CASE WHEN n:Entity THEN 'Entity' ELSE 'ActionNode' END AS nodeType
            ORDER BY coalesce(n.sequence, 0), n.name
            """,
            new { dataset = DatasetId });

        await nodeCursor.ForEachAsync(record =>
        {
            var mapped = MapNode(record["n"].As<INode>(), record["nodeType"].As<string>());
            nodes[mapped.Id] = mapped;
        });

        var edgeCursor = await session.RunAsync(
            """
            MATCH (a)-[r:OPERATES|PERFORMS|TARGETS|DIRECTED_TO|CAUSES]->(b)
            WHERE a.dataset = $dataset AND b.dataset = $dataset
            RETURN a.id AS source, b.id AS target, type(r) AS relType
            ORDER BY source, target
            """,
            new { dataset = DatasetId });

        await edgeCursor.ForEachAsync(record => edges.Add(MapEdge(record)));
        return new CausalGraphResult { Nodes = nodes.Values.ToArray(), Edges = edges };
    }

    public async Task<CausalGraphResult> TraceBackAsync(
        string targetEntityId,
        CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var nodes = new Dictionary<string, CausalGraphNode>(StringComparer.Ordinal);
        var edges = new Dictionary<string, CausalGraphEdge>(StringComparer.Ordinal);
        var actionIds = new HashSet<string>(StringComparer.Ordinal);
        var entityIds = new HashSet<string>(StringComparer.Ordinal);

        var cursor = await session.RunAsync(
            """
            MATCH (target:Entity {id: $targetEntityId, dataset: $dataset})
            MATCH (terminal:ActionNode {dataset: $dataset, isCausalTerminal: true})-[:TARGETS]->(target)
            MATCH p=(ancestor:ActionNode {dataset: $dataset})-[:CAUSES*0..12]->(terminal)
            UNWIND nodes(p) AS action
            WITH DISTINCT action
            OPTIONAL MATCH (actor:Entity {dataset: $dataset})-[:PERFORMS]->(action)
            OPTIONAL MATCH (action)-[:TARGETS]->(actionTarget:Entity {dataset: $dataset})
            OPTIONAL MATCH (action)-[:DIRECTED_TO]->(recipient:Entity {dataset: $dataset})
            RETURN action, actor, actionTarget, recipient
            ORDER BY action.sequence
            """,
            new { targetEntityId, dataset = DatasetId });

        await cursor.ForEachAsync(record =>
        {
            var action = MapNode(record["action"].As<INode>(), "ActionNode");
            nodes[action.Id] = action;
            actionIds.Add(action.Id);

            var actorNode = record["actor"].As<INode?>();
            if (actorNode is not null)
            {
                var actor = MapNode(actorNode, "Entity");
                nodes[actor.Id] = actor;
                entityIds.Add(actor.Id);
                AddEdge(edges, actor.Id, action.Id, "PERFORMS");
            }

            var targetNode = record["actionTarget"].As<INode?>();
            if (targetNode is not null)
            {
                var target = MapNode(targetNode, "Entity");
                nodes[target.Id] = target;
                entityIds.Add(target.Id);
                AddEdge(edges, action.Id, target.Id, "TARGETS");
            }

            var recipientNode = record["recipient"].As<INode?>();
            if (recipientNode is not null)
            {
                var recipient = MapNode(recipientNode, "Entity");
                nodes[recipient.Id] = recipient;
                entityIds.Add(recipient.Id);
                AddEdge(edges, action.Id, recipient.Id, "DIRECTED_TO");
            }
        });

        if (actionIds.Count > 0)
        {
            var causalCursor = await session.RunAsync(
                """
                MATCH (a:ActionNode {dataset: $dataset})-[r:CAUSES]->(b:ActionNode {dataset: $dataset})
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id AS source, b.id AS target, type(r) AS relType
                ORDER BY a.sequence, b.sequence
                """,
                new { dataset = DatasetId, ids = actionIds.ToArray() });

            await causalCursor.ForEachAsync(record =>
            {
                var edge = MapEdge(record);
                edges[edge.Id] = edge;
            });
        }

        if (entityIds.Count > 0)
        {
            var staticCursor = await session.RunAsync(
                """
                MATCH (a:Entity {dataset: $dataset})-[r:OPERATES]->(b:Entity {dataset: $dataset})
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id AS source, b.id AS target, type(r) AS relType
                """,
                new { dataset = DatasetId, ids = entityIds.ToArray() });

            await staticCursor.ForEachAsync(record =>
            {
                var edge = MapEdge(record);
                edges[edge.Id] = edge;
            });
        }

        return new CausalGraphResult
        {
            Nodes = nodes.Values.ToArray(),
            Edges = edges.Values.ToArray()
        };
    }

    public async Task<IReadOnlyList<EntityTimelinePoint>> GetEntityTimelineAsync(
        string entityId,
        CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var cursor = await session.RunAsync(
            """
            MATCH (e:Entity {id: $entityId, dataset: $dataset})-[:HAS_STATE]->(s:StateNode {dataset: $dataset})
            RETURN s.timestamp AS timestamp,
                   s.location AS location,
                   s.action AS action,
                   s.actionObject AS actionObject,
                   s.directResult AS directResult,
                   s.updatedState AS updatedState,
                   s.sourceBasis AS sourceBasis,
                   s.sequence AS sequence,
                   s.latitude AS latitude,
                   s.longitude AS longitude
            ORDER BY s.sequence
            """,
            new { entityId, dataset = DatasetId });

        var result = new List<EntityTimelinePoint>();
        await cursor.ForEachAsync(record => result.Add(new EntityTimelinePoint(
            record["timestamp"].As<string>(),
            record["location"].As<string>(),
            record["action"].As<string>(),
            record["actionObject"].As<string>(),
            record["directResult"].As<string>(),
            record["updatedState"].As<string>(),
            record["sourceBasis"].As<string>(),
            (int)record["sequence"].As<long>(),
            record["latitude"].As<double?>(),
            record["longitude"].As<double?>())));

        return result;
    }

    public async Task<CausalStatistics> GetStatisticsAsync(CancellationToken cancellationToken = default)
    {
        await using var session = _driver.AsyncSession();
        var cursor = await session.RunAsync(
            """
            CALL {
              MATCH (e:Entity {dataset: $dataset})
              RETURN count(e) AS entityCount,
                     count(DISTINCT e.ontologyType) AS entityTypeCount,
                     count(DISTINCT e.operationalRole) AS operationalRoleCount
            }
            CALL {
              MATCH (a:ActionNode {dataset: $dataset})
              RETURN count(a) AS actionCount
            }
            CALL {
              MATCH (s:StateNode {dataset: $dataset})
              RETURN count(s) AS stateCount
            }
            CALL {
              MATCH (a)-[r]->(b)
              WHERE a.dataset = $dataset AND b.dataset = $dataset
              RETURN count(r) AS relationshipCount,
                     count(DISTINCT type(r)) AS relationTypeCount,
                     count(CASE WHEN type(r) = 'CAUSES' THEN 1 END) AS causalRelationCount
            }
            RETURN entityCount, actionCount, stateCount, relationshipCount,
                   entityTypeCount, operationalRoleCount, relationTypeCount, causalRelationCount
            """,
            new { dataset = DatasetId });

        var record = await cursor.SingleAsync();
        return new CausalStatistics(
            (int)record["entityCount"].As<long>(),
            (int)record["actionCount"].As<long>(),
            (int)record["stateCount"].As<long>(),
            (int)record["relationshipCount"].As<long>(),
            (int)record["entityTypeCount"].As<long>(),
            (int)record["operationalRoleCount"].As<long>(),
            (int)record["relationTypeCount"].As<long>(),
            (int)record["causalRelationCount"].As<long>());
    }

    private static CausalGraphNode MapNode(INode node, string type)
    {
        if (type == "Entity")
        {
            return new CausalGraphNode
            {
                Id = node["id"].As<string>(),
                Label = node["name"].As<string>(),
                Type = type,
                Category = node.Properties.TryGetValue("ontologyType", out var ontologyType)
                    ? ontologyType?.ToString()
                    : null,
                Role = node.Properties.TryGetValue("operationalRole", out var role)
                    ? role?.ToString()
                    : null,
                Properties = node.Properties.ToDictionary(x => x.Key, x => (object?)x.Value)
            };
        }

        return new CausalGraphNode
        {
            Id = node["id"].As<string>(),
            Label = node["name"].As<string>(),
            Type = type,
            Category = "Action",
            Role = node.Properties.TryGetValue("actionType", out var actionType)
                ? actionType?.ToString()
                : "action",
            Properties = node.Properties.ToDictionary(x => x.Key, x => (object?)x.Value)
        };
    }

    private static CausalGraphEdge MapEdge(IRecord record)
    {
        var source = record["source"].As<string>();
        var target = record["target"].As<string>();
        var type = record["relType"].As<string>();
        return new CausalGraphEdge
        {
            Id = $"{type}:{source}:{target}",
            Source = source,
            Target = target,
            Type = type
        };
    }

    private static void AddEdge(
        IDictionary<string, CausalGraphEdge> edges,
        string source,
        string target,
        string type)
    {
        var id = $"{type}:{source}:{target}";
        edges[id] = new CausalGraphEdge { Id = id, Source = source, Target = target, Type = type };
    }

    public async ValueTask DisposeAsync()
    {
        await _driver.DisposeAsync();
        GC.SuppressFinalize(this);
    }
}
