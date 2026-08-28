using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Neo4j.Driver;

namespace Aegis.Infrastructure.Neo4j;

public class Neo4jGraphRepository : IGraphRepository, IAsyncDisposable
{
    private readonly IDriver _driver;
    private readonly ILogger<Neo4jGraphRepository> _logger;

    public Neo4jGraphRepository(IConfiguration configuration, ILogger<Neo4jGraphRepository> logger)
    {
        _logger = logger;
        var uri = configuration["ConnectionStrings:Neo4j"] ?? "bolt://localhost:7687";
        var user = configuration["Neo4j:User"] ?? "neo4j";
        var password = configuration["Neo4j:Password"] ?? "aegis2026!";
        _driver = GraphDatabase.Driver(uri, AuthTokens.Basic(user, password));
    }

    // ── Facilities ──
    public async Task<IEnumerable<Facility>> GetAllFacilitiesAsync()
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (f:Facility)
            OPTIONAL MATCH (f)-[:LOCATED_AT]->(l:Location)
            OPTIONAL MATCH (f)-[:HAS_SENSOR]->(s:Sensor)
            OPTIONAL MATCH (f)-[:HAS_ASSET]->(a:Asset)
            RETURN f, l, collect(DISTINCT s) as sensors, collect(DISTINCT a) as assets
        ");

        var facilities = new List<Facility>();
        await result.ForEachAsync(record =>
        {
            var node = record["f"].As<INode>();
            var location = record["l"].As<INode?>();
            facilities.Add(new Facility
            {
                FacilityId = node["facilityId"].As<string>(),
                Name = node["name"].As<string>(),
                Type = node["type"].As<string>(),
                Status = node["status"].As<string>(),
                Criticality = node["criticality"].As<string>(),
                Latitude = location?["latitude"].As<double>() ?? 0,
                Longitude = location?["longitude"].As<double>() ?? 0,
                Sensors = record["sensors"].As<List<INode>>()
                    .Select(s => new Sensor { SensorId = s["sensorId"].As<string>(), Name = s["name"].As<string>() }).ToList(),
                Assets = record["assets"].As<List<INode>>()
                    .Select(a => new Asset { AssetId = a["assetId"].As<string>(), Name = a["name"].As<string>() }).ToList()
            });
        });

        return facilities;
    }

    public async Task<Facility?> GetFacilityByIdAsync(string facilityId)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (f:Facility {facilityId: $facilityId})
            OPTIONAL MATCH (f)-[:LOCATED_AT]->(l:Location)
            RETURN f, l
        ", new { facilityId });

        var record = await result.SingleAsync();
        if (record == null) return null;

        var node = record["f"].As<INode>();
        var location = record["l"].As<INode?>();

        return new Facility
        {
            FacilityId = node["facilityId"].As<string>(),
            Name = node["name"].As<string>(),
            Type = node["type"].As<string>(),
            Status = node["status"].As<string>(),
            Criticality = node["criticality"].As<string>(),
            Latitude = location?["latitude"].As<double>() ?? 0,
            Longitude = location?["longitude"].As<double>() ?? 0
        };
    }

    // ── Events ──
    public async Task<IEnumerable<Event>> GetEventsAsync(EventFilter? filter = null)
    {
        await using var session = _driver.AsyncSession();
        var eventWhere = "WHERE true ";
        var parameters = new Dictionary<string, object>();

        if (filter?.EventType != null)
        {
            eventWhere += "AND e.eventType = $eventType ";
            parameters["eventType"] = filter.EventType;
        }
        if (filter?.MinSeverity != null)
        {
            eventWhere += "AND e.severity >= $minSeverity ";
            parameters["minSeverity"] = filter.MinSeverity.Value;
        }
        if (filter?.Severity != null)
        {
            eventWhere += "AND e.severity = $severity ";
            parameters["severity"] = filter.Severity.Value;
        }
        if (filter?.From != null)
        {
            eventWhere += "AND e.timestamp >= datetime($from) ";
            parameters["from"] = filter.From.Value.ToString("o");
        }
        if (filter?.To != null)
        {
            eventWhere += "AND e.timestamp <= datetime($to) ";
            parameters["to"] = filter.To.Value.ToString("o");
        }

        var facilityMatch = "OPTIONAL MATCH (e)-[:OCCURS_AT]->(f:Facility)";
        if (filter?.FacilityId != null)
        {
            facilityMatch = "MATCH (e)-[:OCCURS_AT]->(f:Facility {facilityId: $facilityId})";
            parameters["facilityId"] = filter.FacilityId;
        }

        // Use a higher limit when a time-window filter is set (e.g. InferenceEngine)
        // to avoid missing events during burst scenarios.
        var limit = filter?.From != null ? 500 : 100;

        var query = $@"
            MATCH (e:Event)
            {eventWhere}
            {facilityMatch}
            OPTIONAL MATCH (e)-[:INVOLVES_PERSON]->(p:Person)
            RETURN e, f.facilityId as facilityId, f.name as facilityName,
                   p.personId as personId, p.name as personName
            ORDER BY e.timestamp DESC
            LIMIT {limit}
        ";

        var result = await session.RunAsync(query, parameters);
        return await MapEventsAsync(result);
    }

    public async Task<IEnumerable<Event>> GetEventsByFacilityAsync(string facilityId)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (e:Event)-[:OCCURS_AT]->(f:Facility {facilityId: $facilityId})
            OPTIONAL MATCH (e)-[:INVOLVES_PERSON]->(p:Person)
            RETURN e, f.facilityId as facilityId, f.name as facilityName,
                   p.personId as personId, p.name as personName
            ORDER BY e.timestamp DESC
        ", new { facilityId });

        return await MapEventsAsync(result);
    }

    public async Task<Event?> GetEventByIdAsync(string eventId)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (e:Event {eventId: $eventId})
            OPTIONAL MATCH (e)-[:OCCURS_AT]->(f:Facility)
            OPTIONAL MATCH (e)-[:INVOLVES_PERSON]->(p:Person)
            RETURN e, f.facilityId as facilityId, f.name as facilityName,
                   p.personId as personId, p.name as personName
        ", new { eventId });

        var events = await MapEventsAsync(result);
        return events.FirstOrDefault();
    }

    // ── Persons ──
    public async Task<IEnumerable<Person>> GetAllPersonsAsync()
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (p:Person)
            OPTIONAL MATCH (p)-[:BELONGS_TO]->(o:Organization)
            RETURN p, o.orgId as orgId, o.name as orgName
        ");

        var persons = new List<Person>();
        await result.ForEachAsync(record =>
        {
            var node = record["p"].As<INode>();
            persons.Add(new Person
            {
                PersonId = node["personId"].As<string>(),
                Name = node["name"].As<string>(),
                Role = node["role"].As<string>(),
                Clearance = node["clearance"].As<string>(),
                PersonType = node.Labels.Contains("Contractor") ? "Contractor" : "Employee",
                OrganizationId = record["orgId"].As<string?>(),
                OrganizationName = record["orgName"].As<string?>()
            });
        });

        return persons;
    }

    public async Task<Person?> GetPersonByIdAsync(string personId)
    {
        var persons = await GetAllPersonsAsync();
        return persons.FirstOrDefault(p => p.PersonId == personId);
    }

    // ── Risk Cases ──
    public async Task<IEnumerable<RiskCase>> GetAllRiskCasesAsync()
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (rc:RiskCase)
            OPTIONAL MATCH (rc)-[:LINKED_FACILITY]->(f:Facility)
            OPTIONAL MATCH (rc)-[:LINKED_EVENT]->(e:Event)
            OPTIONAL MATCH (rc)-[:LINKED_PERSON]->(p:Person)
            RETURN rc, f.name as facilityName,
                   collect(DISTINCT e.eventId) as eventIds,
                   collect(DISTINCT p.name) as personNames
        ");

        var cases = new List<RiskCase>();
        await result.ForEachAsync(record =>
        {
            var node = record["rc"].As<INode>();
            cases.Add(new RiskCase
            {
                CaseId = node["caseId"].As<string>(),
                Title = node["title"].As<string>(),
                Status = node["status"].As<string>(),
                Confidence = node["confidence"].As<double>(),
                RiskScore = node["riskScore"].As<double>(),
                Description = node["description"].As<string>(),
                CreatedAt = node["createdAt"].As<DateTimeOffset>().DateTime,
                LinkedFacilityId = record["facilityName"].As<string?>(),
                LinkedEventIds = record["eventIds"].As<List<string>>(),
                LinkedPersonIds = record["personNames"].As<List<string>>()
            });
        });

        return cases;
    }

    public async Task<RiskCase?> GetRiskCaseByIdAsync(string caseId)
    {
        var cases = await GetAllRiskCasesAsync();
        return cases.FirstOrDefault(c => c.CaseId == caseId);
    }

    // ── Graph Exploration ──
    public async Task<GraphExplorationResult> ExploreNodeAsync(string nodeId, int depth = 2, List<string>? excludeLabels = null)
    {
        await using var session = _driver.AsyncSession();

        // Build APOC labelFilter: "-Label1|-Label2" to exclude unwanted node types
        var labelFilter = "";
        if (excludeLabels is { Count: > 0 })
            labelFilter = string.Join("|", excludeLabels.Select(l => $"-{l}"));

        var result = await session.RunAsync($@"
            MATCH (n)
            WHERE n.facilityId = $nodeId OR n.eventId = $nodeId OR n.personId = $nodeId
               OR n.assetId = $nodeId OR n.caseId = $nodeId OR n.orgId = $nodeId
               OR n.sensorId = $nodeId OR n.locationId = $nodeId OR n.docId = $nodeId
            CALL apoc.path.subgraphAll(n, {{maxLevel: $depth, labelFilter: $labelFilter}})
            YIELD nodes, relationships
            RETURN nodes, relationships
        ", new { nodeId, depth, labelFilter });

        var graphResult = new GraphExplorationResult();
        var nodeSet = new HashSet<string>();
        var edgeSet = new HashSet<string>();

        await result.ForEachAsync(record =>
        {
            foreach (var node in record["nodes"].As<List<INode>>())
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                {
                    graphResult.Nodes.Add(new GraphNode
                    {
                        Id = id,
                        Label = GetNodeLabel(node),
                        Type = node.Labels.FirstOrDefault() ?? "Unknown",
                        Properties = node.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
                    });
                }
            }

            foreach (var rel in record["relationships"].As<List<IRelationship>>())
            {
                var edgeId = $"{rel.StartNodeElementId}-{rel.Type}-{rel.EndNodeElementId}";
                if (edgeSet.Add(edgeId))
                {
                    graphResult.Edges.Add(new GraphEdge
                    {
                        Id = edgeId,
                        Source = rel.StartNodeElementId,
                        Target = rel.EndNodeElementId,
                        Type = rel.Type,
                        Properties = rel.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
                    });
                }
            }
        });

        // Fix edge source/target to use our IDs
        var elementIdToId = new Dictionary<string, string>();
        await using var session2 = _driver.AsyncSession();
        var allNodes = await session2.RunAsync(@"
            MATCH (n) WHERE n.facilityId IS NOT NULL OR n.eventId IS NOT NULL
               OR n.personId IS NOT NULL OR n.assetId IS NOT NULL OR n.caseId IS NOT NULL
               OR n.orgId IS NOT NULL OR n.sensorId IS NOT NULL OR n.locationId IS NOT NULL
               OR n.docId IS NOT NULL OR n.name IS NOT NULL
            RETURN elementId(n) as eid, n
        ");
        await allNodes.ForEachAsync(r =>
        {
            var eid = r["eid"].As<string>();
            var n = r["n"].As<INode>();
            elementIdToId[eid] = GetNodeId(n);
        });

        foreach (var edge in graphResult.Edges)
        {
            if (elementIdToId.TryGetValue(edge.Source, out var src)) edge.Source = src;
            if (elementIdToId.TryGetValue(edge.Target, out var tgt)) edge.Target = tgt;
        }

        return graphResult;
    }

    public async Task<IEnumerable<GraphRelationship>> GetRelationshipsAsync(string nodeId)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (n)-[r]-(m)
            WHERE n.facilityId = $nodeId OR n.eventId = $nodeId OR n.personId = $nodeId
               OR n.assetId = $nodeId OR n.caseId = $nodeId
            RETURN type(r) as relType, n, m, r
        ", new { nodeId });

        var rels = new List<GraphRelationship>();
        await result.ForEachAsync(record =>
        {
            var src = record["n"].As<INode>();
            var tgt = record["m"].As<INode>();
            rels.Add(new GraphRelationship
            {
                Type = record["relType"].As<string>(),
                SourceId = GetNodeId(src),
                SourceLabel = src.Labels.FirstOrDefault() ?? "",
                TargetId = GetNodeId(tgt),
                TargetLabel = tgt.Labels.FirstOrDefault() ?? ""
            });
        });

        return rels;
    }

    // ── Link Analysis ──
    public async Task<LinkAnalysisResult> FindShortestPathsAsync(List<string> nodeIds, int maxDepth = 6)
    {
        var result = new LinkAnalysisResult();
        var nodeSet = new HashSet<string>();
        var edgeSet = new HashSet<string>();

        // For each pair of nodes, find all shortest paths
        for (var i = 0; i < nodeIds.Count; i++)
        {
            for (var j = i + 1; j < nodeIds.Count; j++)
            {
                await using var session = _driver.AsyncSession();
                var cypher = $@"
                    MATCH (a), (b)
                    WHERE (a.facilityId = $idA OR a.eventId = $idA OR a.personId = $idA
                           OR a.assetId = $idA OR a.caseId = $idA OR a.orgId = $idA
                           OR a.sensorId = $idA OR a.locationId = $idA)
                      AND (b.facilityId = $idB OR b.eventId = $idB OR b.personId = $idB
                           OR b.assetId = $idB OR b.caseId = $idB OR b.orgId = $idB
                           OR b.sensorId = $idB OR b.locationId = $idB)
                    MATCH p = allShortestPaths((a)-[*..{maxDepth}]-(b))
                    RETURN p
                    LIMIT 5
                ";

                try
                {
                    var queryResult = await session.RunAsync(cypher, new { idA = nodeIds[i], idB = nodeIds[j] });

                    await queryResult.ForEachAsync(record =>
                    {
                        var path = record["p"].As<IPath>();
                        var pathNodes = path.Nodes.ToList();
                        var pathRels = path.Relationships.ToList();

                        var fromId = GetNodeId(pathNodes.First());
                        var toId = GetNodeId(pathNodes.Last());

                        var discoveredPath = new DiscoveredPath
                        {
                            FromId = fromId,
                            FromLabel = GetNodeLabel(pathNodes.First()),
                            ToId = toId,
                            ToLabel = GetNodeLabel(pathNodes.Last()),
                            Length = pathRels.Count,
                            NodeSequence = pathNodes.Select(n => $"{n.Labels.FirstOrDefault()}:{GetNodeLabel(n)}").ToList(),
                            RelationshipSequence = pathRels.Select(r => r.Type).ToList(),
                            Relevance = 1.0 / pathRels.Count // shorter paths = higher relevance
                        };
                        result.Paths.Add(discoveredPath);

                        // Collect all nodes and edges for the combined graph
                        foreach (var node in pathNodes)
                        {
                            var id = GetNodeId(node);
                            if (nodeSet.Add(id))
                            {
                                result.Graph.Nodes.Add(MapToGraphNode(node));
                            }
                        }

                        foreach (var rel in pathRels)
                        {
                            var edgeId = $"{GetNodeId(pathNodes[pathRels.IndexOf(rel)])}-{rel.Type}-{GetNodeId(pathNodes[pathRels.IndexOf(rel) + 1])}";
                            if (edgeSet.Add(edgeId))
                            {
                                result.Graph.Edges.Add(new GraphEdge
                                {
                                    Id = edgeId,
                                    Source = GetNodeId(pathNodes[pathRels.IndexOf(rel)]),
                                    Target = GetNodeId(pathNodes[pathRels.IndexOf(rel) + 1]),
                                    Type = rel.Type,
                                    Properties = rel.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
                                });
                            }
                        }
                    });
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "No path found between {A} and {B}", nodeIds[i], nodeIds[j]);
                }
            }
        }

        // Sort paths: hidden links (length > 1) first, then by relevance
        result.Paths = result.Paths
            .OrderByDescending(p => p.Length > 1 ? 1 : 0)
            .ThenByDescending(p => p.Relevance)
            .ToList();

        return result;
    }

    public async Task<GraphExplorationResult> GetCaseGraphAsync(string caseId)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            MATCH (rc:RiskCase {caseId: $caseId})
            OPTIONAL MATCH (rc)-[r1:LINKED_EVENT]->(e:Event)
            OPTIONAL MATCH (rc)-[r2:LINKED_FACILITY]->(f:Facility)
            OPTIONAL MATCH (rc)-[r3:LINKED_PERSON]->(p:Person)
            OPTIONAL MATCH (e)-[r4:OCCURS_AT]->(f2:Facility)
            OPTIONAL MATCH (e)-[r5:INVOLVES_PERSON]->(p2:Person)
            OPTIONAL MATCH (e)-[r6:INVOLVES_ASSET]->(a:Asset)
            OPTIONAL MATCH (p)-[r7:BELONGS_TO]->(o:Organization)
            OPTIONAL MATCH (p2)-[r8:BELONGS_TO]->(o2:Organization)
            OPTIONAL MATCH (f)-[r9:LOCATED_AT]->(l:Location)
            OPTIONAL MATCH (f2)-[r10:LOCATED_AT]->(l2:Location)
            RETURN rc, collect(DISTINCT e) as events, collect(DISTINCT f) as facilities,
                   collect(DISTINCT f2) as facilities2, collect(DISTINCT p) as persons,
                   collect(DISTINCT p2) as persons2, collect(DISTINCT a) as assets,
                   collect(DISTINCT o) as orgs, collect(DISTINCT o2) as orgs2,
                   collect(DISTINCT l) + collect(DISTINCT l2) as locations
        ", new { caseId });

        var graphResult = new GraphExplorationResult();
        var nodeSet = new HashSet<string>();

        await result.ForEachAsync(record =>
        {
            // Add RiskCase node
            var rcNode = record["rc"].As<INode>();
            var rcId = GetNodeId(rcNode);
            if (nodeSet.Add(rcId))
                graphResult.Nodes.Add(MapToGraphNode(rcNode));

            // Add all related nodes and edges
            AddNodesAndEdges(record, "events", rcId, "LINKED_EVENT", graphResult, nodeSet);
            AddNodesAndEdges(record, "facilities", rcId, "LINKED_FACILITY", graphResult, nodeSet);
            AddNodesAndEdges(record, "persons", rcId, "LINKED_PERSON", graphResult, nodeSet);

            foreach (var node in record["facilities2"].As<List<INode>>())
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                    graphResult.Nodes.Add(MapToGraphNode(node));
            }
            foreach (var node in record["persons2"].As<List<INode>>())
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                    graphResult.Nodes.Add(MapToGraphNode(node));
            }
            foreach (var node in record["assets"].As<List<INode>>())
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                    graphResult.Nodes.Add(MapToGraphNode(node));
            }
            foreach (var node in record["orgs"].As<List<INode>>().Concat(record["orgs2"].As<List<INode>>()))
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                    graphResult.Nodes.Add(MapToGraphNode(node));
            }
            foreach (var node in record["locations"].As<List<INode>>())
            {
                var id = GetNodeId(node);
                if (nodeSet.Add(id))
                    graphResult.Nodes.Add(MapToGraphNode(node));
            }
        });

        // Build edges from relationships
        await using var session2 = _driver.AsyncSession();
        var edgeResult = await session2.RunAsync(@"
            MATCH (rc:RiskCase {caseId: $caseId})-[r]->(n)
            RETURN type(r) as relType,
                   rc.caseId as srcId, labels(rc)[0] as srcLabel,
                   coalesce(n.eventId, n.facilityId, n.personId, n.name) as tgtId
            UNION
            MATCH (rc:RiskCase {caseId: $caseId})-[:LINKED_EVENT]->(e:Event)-[r]->(n)
            RETURN type(r) as relType,
                   e.eventId as srcId, labels(e)[0] as srcLabel,
                   coalesce(n.facilityId, n.personId, n.assetId, n.name) as tgtId
            UNION
            MATCH (rc:RiskCase {caseId: $caseId})-[:LINKED_PERSON]->(p:Person)-[r:BELONGS_TO]->(o:Organization)
            RETURN type(r) as relType,
                   p.personId as srcId, 'Person' as srcLabel,
                   o.orgId as tgtId
            UNION
            MATCH (rc:RiskCase {caseId: $caseId})-[:LINKED_EVENT]->(e:Event)-[:INVOLVES_PERSON]->(p:Person)-[r:BELONGS_TO]->(o:Organization)
            RETURN type(r) as relType,
                   p.personId as srcId, 'Person' as srcLabel,
                   o.orgId as tgtId
            UNION
            MATCH (rc:RiskCase {caseId: $caseId})-[:LINKED_FACILITY]->(f:Facility)-[r:LOCATED_AT]->(l:Location)
            RETURN type(r) as relType,
                   f.facilityId as srcId, 'Facility' as srcLabel,
                   l.locationId as tgtId
            UNION
            MATCH (rc:RiskCase {caseId: $caseId})-[:LINKED_EVENT]->(e:Event)-[:OCCURS_AT]->(f:Facility)-[r:LOCATED_AT]->(l:Location)
            RETURN type(r) as relType,
                   f.facilityId as srcId, 'Facility' as srcLabel,
                   l.locationId as tgtId
        ", new { caseId });

        await edgeResult.ForEachAsync(r =>
        {
            var src = r["srcId"].As<string?>();
            var tgt = r["tgtId"].As<string?>();
            if (src != null && tgt != null)
            {
                graphResult.Edges.Add(new GraphEdge
                {
                    Id = $"{src}-{r["relType"].As<string>()}-{tgt}",
                    Source = src,
                    Target = tgt,
                    Type = r["relType"].As<string>()
                });
            }
        });

        return graphResult;
    }

    // ── Timeline ──
    public async Task<IEnumerable<Event>> GetTimelineAsync(DateTime from, DateTime to, string? facilityId = null)
    {
        await using var session = _driver.AsyncSession();
        var query = facilityId != null
            ? @"MATCH (e:Event)-[:OCCURS_AT]->(f:Facility {facilityId: $facilityId})
               OPTIONAL MATCH (e)-[:INVOLVES_PERSON]->(p:Person)
               WHERE e.timestamp >= datetime($from) AND e.timestamp <= datetime($to)
               RETURN e, f.facilityId as facilityId, f.name as facilityName,
                      p.personId as personId, p.name as personName
               ORDER BY e.timestamp"
            : @"MATCH (e:Event)
               OPTIONAL MATCH (e)-[:OCCURS_AT]->(f:Facility)
               OPTIONAL MATCH (e)-[:INVOLVES_PERSON]->(p:Person)
               WHERE e.timestamp >= datetime($from) AND e.timestamp <= datetime($to)
               RETURN e, f.facilityId as facilityId, f.name as facilityName,
                      p.personId as personId, p.name as personName
               ORDER BY e.timestamp";

        var parameters = new Dictionary<string, object>
        {
            ["from"] = from.ToString("o"),
            ["to"] = to.ToString("o")
        };
        if (facilityId != null) parameters["facilityId"] = facilityId;

        var result = await session.RunAsync(query, parameters);
        return await MapEventsAsync(result);
    }

    // ── Dashboard Stats ──
    public async Task<DashboardStats> GetDashboardStatsAsync()
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(@"
            OPTIONAL MATCH (f:Facility)
            WITH count(f) as facilities
            OPTIONAL MATCH (e:Event)
            WITH facilities, count(e) as events
            OPTIONAL MATCH (rc:RiskCase) WHERE rc.status IN ['Open', 'Investigating']
            WITH facilities, events, count(rc) as openCases
            OPTIONAL MATCH (ce:Event) WHERE ce.severity >= 4
            WITH facilities, events, openCases, count(ce) as criticalAlerts
            OPTIONAL MATCH (p:Person)
            RETURN facilities, events, openCases, criticalAlerts, count(p) as persons
        ");

        var record = await result.SingleAsync();

        // Event type stats
        var typeResult = await session.RunAsync(@"
            MATCH (e:Event)
            RETURN e.eventType as type, count(e) as count
            ORDER BY count DESC
        ");
        var typeStats = new List<EventTypeStat>();
        await typeResult.ForEachAsync(r =>
            typeStats.Add(new EventTypeStat { Type = r["type"].As<string>(), Count = r["count"].As<int>() }));

        // Severity stats
        var sevResult = await session.RunAsync(@"
            MATCH (e:Event)
            RETURN e.severity as severity, count(e) as count
            ORDER BY severity
        ");
        var sevStats = new List<SeverityStat>();
        await sevResult.ForEachAsync(r =>
            sevStats.Add(new SeverityStat { Severity = r["severity"].As<int>(), Count = r["count"].As<int>() }));

        return new DashboardStats
        {
            TotalFacilities = record["facilities"].As<int>(),
            TotalEvents = record["events"].As<int>(),
            OpenCases = record["openCases"].As<int>(),
            CriticalAlerts = record["criticalAlerts"].As<int>(),
            TotalPersons = record["persons"].As<int>(),
            EventsByType = typeStats,
            EventsBySeverity = sevStats
        };
    }

    // ── Seed ──
    public async Task ClearAllDataAsync()
    {
        await using var session = _driver.AsyncSession();
        // Drop all constraints and indexes, then delete all nodes and relationships
        await session.RunAsync("MATCH (n) DETACH DELETE n");
        _logger.LogInformation("Cleared all data from Neo4j");
    }

    // ── Write Operations ──
    public async Task<Event> CreateEventAsync(Event evt)
    {
        await using var session = _driver.AsyncSession();

        // Build metadata properties for inline storage
        var metaProps = new Dictionary<string, object>();
        if (evt.Metadata != null)
        {
            foreach (var kvp in evt.Metadata)
            {
                // Neo4j only supports primitives; skip complex objects
                if (kvp.Value is string or int or long or double or float or bool)
                    metaProps[$"meta_{kvp.Key}"] = kvp.Value;
                else
                    metaProps[$"meta_{kvp.Key}"] = kvp.Value?.ToString() ?? "";
            }
        }

        var parameters = new Dictionary<string, object>
        {
            ["eventId"] = evt.EventId,
            ["eventType"] = evt.EventType,
            ["description"] = evt.Description,
            ["severity"] = evt.Severity,
            ["timestamp"] = evt.Timestamp.ToString("o"),
        };

        // Merge metadata into parameters
        foreach (var kvp in metaProps)
            parameters[kvp.Key] = kvp.Value;

        // Build SET clause for metadata
        var metaSet = string.Join(", ", metaProps.Keys.Select(k => $"e.{k} = ${k}"));
        var metaClause = metaSet.Length > 0 ? $", {metaSet}" : "";

        var createQuery = $@"
            CREATE (e:Event {{
                eventId: $eventId,
                eventType: $eventType,
                description: $description,
                severity: $severity,
                timestamp: datetime($timestamp)
            }})
            SET e.createdAt = datetime(){metaClause}
            RETURN e
        ";

        string? facilityName = null;
        string? personName = null;

        await session.ExecuteWriteAsync(async tx =>
        {
            var createResult = await tx.RunAsync(createQuery, parameters);
            await createResult.ConsumeAsync();

            // Create OCCURS_AT relationship to facility
            if (!string.IsNullOrEmpty(evt.FacilityId))
            {
                var facResult = await tx.RunAsync(@"
                    MATCH (e:Event {eventId: $eventId})
                    MATCH (f:Facility {facilityId: $facilityId})
                    MERGE (e)-[:OCCURS_AT]->(f)
                    RETURN f.name as facilityName
                ", new { eventId = evt.EventId, facilityId = evt.FacilityId });

                var facRecord = await facResult.SingleAsync();
                facilityName = facRecord?["facilityName"]?.As<string>();
            }

            // Create INVOLVES_PERSON relationship
            if (!string.IsNullOrEmpty(evt.PersonId))
            {
                var perResult = await tx.RunAsync(@"
                    MATCH (e:Event {eventId: $eventId})
                    MATCH (p:Person {personId: $personId})
                    MERGE (e)-[:INVOLVES_PERSON]->(p)
                    RETURN p.name as personName
                ", new { eventId = evt.EventId, personId = evt.PersonId });

                var perRecord = await perResult.SingleAsync();
                personName = perRecord?["personName"]?.As<string>();
            }
        });

        _logger.LogInformation("Created event {EventId} in Neo4j (facility={Facility}, person={Person})",
            evt.EventId, evt.FacilityId, evt.PersonId);

        return new Event
        {
            EventId = evt.EventId,
            EventType = evt.EventType,
            Description = evt.Description,
            Severity = evt.Severity,
            Timestamp = evt.Timestamp,
            FacilityId = evt.FacilityId,
            FacilityName = facilityName,
            PersonId = evt.PersonId,
            PersonName = personName,
            Metadata = evt.Metadata ?? []
        };
    }

    public async Task CreateRiskCaseAsync(RiskCase riskCase)
    {
        await using var session = _driver.AsyncSession();

        await session.ExecuteWriteAsync(async tx =>
        {
            // Create the RiskCase node
            var createResult = await tx.RunAsync(@"
                CREATE (rc:RiskCase {
                    caseId: $caseId,
                    title: $title,
                    status: $status,
                    confidence: $confidence,
                    riskScore: $riskScore,
                    description: $description,
                    createdAt: datetime()
                })
                RETURN rc.caseId
            ", new
            {
                caseId = riskCase.CaseId,
                title = riskCase.Title,
                status = riskCase.Status,
                confidence = riskCase.Confidence,
                riskScore = riskCase.RiskScore,
                description = riskCase.Description
            });
            await createResult.ConsumeAsync();

            // Link to facility
            if (!string.IsNullOrEmpty(riskCase.LinkedFacilityId))
            {
                var r = await tx.RunAsync(@"
                    MATCH (rc:RiskCase {caseId: $caseId})
                    MATCH (f:Facility {facilityId: $facilityId})
                    MERGE (rc)-[:LINKED_FACILITY]->(f)
                ", new { caseId = riskCase.CaseId, facilityId = riskCase.LinkedFacilityId });
                await r.ConsumeAsync();
            }

            // Link to events
            if (riskCase.LinkedEventIds.Count > 0)
            {
                var r = await tx.RunAsync(@"
                    MATCH (rc:RiskCase {caseId: $caseId})
                    UNWIND $eventIds AS eid
                    MATCH (e:Event {eventId: eid})
                    MERGE (rc)-[:LINKED_EVENT]->(e)
                ", new { caseId = riskCase.CaseId, eventIds = riskCase.LinkedEventIds });
                await r.ConsumeAsync();
            }

            // Link to persons
            if (riskCase.LinkedPersonIds.Count > 0)
            {
                var r = await tx.RunAsync(@"
                    MATCH (rc:RiskCase {caseId: $caseId})
                    UNWIND $personIds AS pid
                    MATCH (p:Person {personId: pid})
                    MERGE (rc)-[:LINKED_PERSON]->(p)
                ", new { caseId = riskCase.CaseId, personIds = riskCase.LinkedPersonIds });
                await r.ConsumeAsync();
            }
        });

        _logger.LogInformation("Created risk case {CaseId}: {Title} (risk={Score:F1})",
            riskCase.CaseId, riskCase.Title, riskCase.RiskScore);
    }

    public async Task SeedDataAsync(string cypherScript)
    {
        await using var session = _driver.AsyncSession();

        // Remove single-line comments (// ...) while preserving the rest
        var cleaned = string.Join('\n',
            cypherScript.Split('\n')
                .Select(line => line.TrimEnd())
                .Select(line =>
                {
                    var trimmed = line.TrimStart();
                    return trimmed.StartsWith("//") ? "" : line;
                })
        );

        // Split by semicolons and run each statement
        var statements = cleaned.Split(';', StringSplitOptions.RemoveEmptyEntries)
            .Select(s => s.Trim())
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();

        _logger.LogInformation("Seed: {Count} statements to execute", statements.Count);

        foreach (var stmt in statements)
        {
            try
            {
                await session.RunAsync(stmt);
                var preview = stmt.Replace('\n', ' ');
                if (preview.Length > 100) preview = preview[..100] + "...";
                _logger.LogInformation("Executed seed statement: {Stmt}", preview);
            }
            catch (Exception ex)
            {
                var preview = stmt.Replace('\n', ' ');
                if (preview.Length > 200) preview = preview[..200] + "...";
                _logger.LogWarning(ex, "Failed to execute: {Stmt}", preview);
            }
        }
    }

    // ── Helpers ──
    private static string GetNodeId(INode node)
    {
        if (node.Properties.TryGetValue("facilityId", out var fid)) return fid.As<string>();
        if (node.Properties.TryGetValue("eventId", out var eid)) return eid.As<string>();
        if (node.Properties.TryGetValue("personId", out var pid)) return pid.As<string>();
        if (node.Properties.TryGetValue("assetId", out var aid)) return aid.As<string>();
        if (node.Properties.TryGetValue("caseId", out var cid)) return cid.As<string>();
        if (node.Properties.TryGetValue("orgId", out var oid)) return oid.As<string>();
        if (node.Properties.TryGetValue("sensorId", out var sid)) return sid.As<string>();
        if (node.Properties.TryGetValue("locationId", out var lid)) return lid.As<string>();
        if (node.Properties.TryGetValue("docId", out var did)) return did.As<string>();
        if (node.Properties.TryGetValue("name", out var name)) return name.As<string>();
        return node.ElementId;
    }

    private static string GetNodeLabel(INode node)
    {
        if (node.Properties.TryGetValue("name", out var name)) return name.As<string>();
        if (node.Properties.TryGetValue("title", out var title)) return title.As<string>();
        return GetNodeId(node);
    }

    private static GraphNode MapToGraphNode(INode node)
    {
        return new GraphNode
        {
            Id = GetNodeId(node),
            Label = GetNodeLabel(node),
            Type = node.Labels.FirstOrDefault() ?? "Unknown",
            Properties = node.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
        };
    }

    private static void AddNodesAndEdges(IRecord record, string key, string sourceId,
        string relType, GraphExplorationResult result, HashSet<string> nodeSet)
    {
        foreach (var node in record[key].As<List<INode>>())
        {
            var id = GetNodeId(node);
            if (nodeSet.Add(id))
                result.Nodes.Add(MapToGraphNode(node));

            result.Edges.Add(new GraphEdge
            {
                Id = $"{sourceId}-{relType}-{id}",
                Source = sourceId,
                Target = id,
                Type = relType
            });
        }
    }

    private static async Task<IEnumerable<Event>> MapEventsAsync(IResultCursor result)
    {
        var events = new List<Event>();
        await result.ForEachAsync(record =>
        {
            var node = record["e"].As<INode>();
            events.Add(new Event
            {
                EventId = node["eventId"].As<string>(),
                EventType = node["eventType"].As<string>(),
                Description = node["description"].As<string>(),
                Severity = node["severity"].As<int>(),
                Timestamp = node["timestamp"].As<DateTimeOffset>().DateTime,
                FacilityId = record["facilityId"].As<string?>(),
                FacilityName = record["facilityName"].As<string?>(),
                PersonId = record["personId"].As<string?>(),
                PersonName = record["personName"].As<string?>(),
                Metadata = node.Properties
                    .Where(kvp => !new[] { "eventId", "eventType", "description", "severity", "timestamp" }.Contains(kvp.Key))
                    .ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
            });
        });
        return events;
    }

    public async ValueTask DisposeAsync()
    {
        await _driver.DisposeAsync();
        GC.SuppressFinalize(this);
    }

    // ── Raw Cypher read (for agent tools) ──

    public async Task<List<Dictionary<string, object>>> ExecuteCypherReadAsync(
        string cypher, Dictionary<string, object>? parameters = null)
    {
        await using var session = _driver.AsyncSession();
        var result = await session.RunAsync(cypher, parameters ?? new Dictionary<string, object>());
        var rows = new List<Dictionary<string, object>>();
        await result.ForEachAsync(record =>
        {
            var row = new Dictionary<string, object>();
            foreach (var key in record.Keys)
            {
                var val = record[key];
                row[key] = val switch
                {
                    INode node => node.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value),
                    IRelationship rel => new Dictionary<string, object>
                    {
                        ["type"] = rel.Type,
                        ["properties"] = rel.Properties.ToDictionary(kvp => kvp.Key, kvp => kvp.Value)
                    },
                    IPath path => $"Path with {path.Nodes.Count()} nodes",
                    _ => val
                };
            }
            rows.Add(row);
        });
        return rows;
    }

    // ── Ontology schema introspection ──

    public async Task<string> GetOntologySchemaAsync()
    {
        await using var session = _driver.AsyncSession();
        var sb = new System.Text.StringBuilder();

        // Node labels and their properties
        sb.AppendLine("=== ONTOLOGY SCHEMA ===\n");
        sb.AppendLine("## Node Types (Labels):");
        var labels = await session.RunAsync("CALL db.labels() YIELD label RETURN label ORDER BY label");
        var labelList = new List<string>();
        await labels.ForEachAsync(r => labelList.Add(r["label"].As<string>()));

        foreach (var label in labelList)
        {
            sb.AppendLine($"\n### :{label}");
            var props = await session.RunAsync(
                $"MATCH (n:`{label}`) WITH n LIMIT 1 RETURN keys(n) AS props");
            await props.ForEachAsync(r =>
            {
                var keys = r["props"].As<List<object>>();
                foreach (var k in keys) sb.AppendLine($"  - {k}");
            });
        }

        // Relationship types
        sb.AppendLine("\n## Relationship Types:");
        var rels = await session.RunAsync(@"
            CALL db.relationshipTypes() YIELD relationshipType
            RETURN relationshipType ORDER BY relationshipType");
        await rels.ForEachAsync(r => sb.AppendLine($"  - {r["relationshipType"].As<string>()}"));

        // Actual relationship patterns (source -> rel -> target)
        sb.AppendLine("\n## Relationship Patterns (how nodes connect):");
        var patterns = await session.RunAsync(@"
            MATCH (a)-[r]->(b)
            WITH DISTINCT labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS tgt
            RETURN src, rel, tgt ORDER BY src, rel");
        await patterns.ForEachAsync(r =>
            sb.AppendLine($"  (:{r["src"].As<string>()}) -[:{r["rel"].As<string>()}]-> (:{r["tgt"].As<string>()})"));

        // Counts
        sb.AppendLine("\n## Node Counts:");
        foreach (var label in labelList)
        {
            var count = await session.RunAsync($"MATCH (n:`{label}`) RETURN count(n) AS c");
            await count.ForEachAsync(r => sb.AppendLine($"  :{label} = {r["c"].As<long>()}"));
        }

        return sb.ToString();
    }
}
