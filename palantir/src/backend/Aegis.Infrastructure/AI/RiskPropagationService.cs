using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Logging;

namespace Aegis.Infrastructure.AI;

/// <summary>
/// Risk Propagation Engine — calculates blast radius from a compromised node.
/// 
/// The algorithm:
///   1. Start at the source node (risk = 10.0 or from the node's actual risk)
///   2. BFS outward through all relationships
///   3. At each depth level, multiply risk by decay factor
///   4. Weight by relationship type (OCCURS_AT and INVOLVES_PERSON = 0.9, CONNECTED_TO = 0.7, etc.)
///   5. Produce "waves" — concentric rings of diminishing risk
///
/// Visual metaphor: drop a stone in water — the ripples spread outward, each weaker than the last.
/// </summary>
public sealed class RiskPropagationService : IRiskPropagationService
{
    private readonly IGraphRepository _repo;
    private readonly ILogger<RiskPropagationService> _logger;

    // Relationship weights — how "strongly" does risk propagate through each type?
    private static readonly Dictionary<string, double> RelationshipWeights = new(StringComparer.OrdinalIgnoreCase)
    {
        ["OCCURS_AT"] = 0.95,
        ["OCCURRED_AT"] = 0.95,
        ["INVOLVES_PERSON"] = 0.90,
        ["INVOLVED_IN"] = 0.90,
        ["LINKED_EVENT"] = 0.85,
        ["LINKED_PERSON"] = 0.85,
        ["LINKED_FACILITY"] = 0.85,
        ["BELONGS_TO"] = 0.75,
        ["OPERATES_IN"] = 0.70,
        ["LOCATED_AT"] = 0.70,
        ["HAS_SENSOR"] = 0.65,
        ["HAS_ASSET"] = 0.65,
        ["CONNECTED_TO"] = 0.80,
        ["INVOLVES_ASSET"] = 0.75,
        ["INVOLVES_SUBSTANCE"] = 0.70,
        ["MONITORS"] = 0.50,
        ["REFERENCES_FACILITY"] = 0.40,
        ["REFERENCES_PERSON"] = 0.40,
    };

    public RiskPropagationService(IGraphRepository repo, ILogger<RiskPropagationService> logger)
    {
        _repo = repo;
        _logger = logger;
    }

    public async Task<RiskPropagationResult> PropagateRiskAsync(
        string sourceNodeId, int maxDepth = 5, double decayFactor = 0.6, CancellationToken ct = default)
    {
        _logger.LogInformation("Risk propagation from {NodeId}, maxDepth={Depth}, decay={Decay}",
            sourceNodeId, maxDepth, decayFactor);

        // Step 1: Get source node info
        var sourceInfo = await GetNodeInfoAsync(sourceNodeId);
        if (sourceInfo == null)
            throw new InvalidOperationException($"Node '{sourceNodeId}' not found in the graph.");

        double sourceRisk = DetermineSourceRisk(sourceInfo);
        var waves = new List<PropagationWave>();
        var allNodes = new List<GraphNodeDto>();
        var allEdges = new List<GraphEdgeDto>();
        var visited = new HashSet<string> { sourceNodeId };
        var currentFrontier = new List<(string Id, double Risk)> { (sourceNodeId, sourceRisk) };

        // Add source node
        allNodes.Add(new GraphNodeDto(
            sourceInfo.Id, sourceInfo.Label, sourceInfo.Type,
            new Dictionary<string, object>(sourceInfo.Properties) { ["propagatedRisk"] = sourceRisk, ["waveDepth"] = 0 }
        ));

        // Step 2: BFS propagation
        for (int depth = 1; depth <= maxDepth && currentFrontier.Count > 0; depth++)
        {
            var waveNodes = new List<PropagatedNode>();
            var nextFrontier = new List<(string Id, double Risk)>();

            foreach (var (parentId, parentRisk) in currentFrontier)
            {
                ct.ThrowIfCancellationRequested();

                var neighbors = await GetNeighborsAsync(parentId);
                foreach (var neighbor in neighbors)
                {
                    if (visited.Contains(neighbor.NodeId))
                        continue;

                    visited.Add(neighbor.NodeId);

                    double relWeight = RelationshipWeights.GetValueOrDefault(neighbor.RelType, 0.5);
                    double propagatedRisk = parentRisk * decayFactor * relWeight;

                    // Floor at 0.1
                    if (propagatedRisk < 0.1) continue;

                    propagatedRisk = Math.Round(propagatedRisk, 2);

                    var propNode = new PropagatedNode(
                        Id: neighbor.NodeId,
                        Label: neighbor.Label,
                        Type: neighbor.NodeType,
                        InheritedRisk: propagatedRisk,
                        RelationshipFromParent: neighbor.RelType,
                        ParentId: parentId,
                        Properties: neighbor.Properties
                    );
                    waveNodes.Add(propNode);
                    nextFrontier.Add((neighbor.NodeId, propagatedRisk));

                    // Build graph
                    var nodeProps = new Dictionary<string, object>(neighbor.Properties)
                    {
                        ["propagatedRisk"] = propagatedRisk,
                        ["waveDepth"] = depth
                    };
                    allNodes.Add(new GraphNodeDto(neighbor.NodeId, neighbor.Label, neighbor.NodeType, nodeProps));
                    allEdges.Add(new GraphEdgeDto(
                        $"prop-{parentId}-{neighbor.NodeId}",
                        parentId, neighbor.NodeId, neighbor.RelType,
                        new Dictionary<string, object> { ["propagatedRisk"] = propagatedRisk }
                    ));
                }
            }

            if (waveNodes.Count > 0)
            {
                double waveRisk = waveNodes.Max(n => n.InheritedRisk);
                waves.Add(new PropagationWave(
                    Depth: depth,
                    RiskLevel: Math.Round(waveRisk, 2),
                    RiskCategory: CategorizeRisk(waveRisk),
                    Nodes: waveNodes.OrderByDescending(n => n.InheritedRisk).ToList()
                ));
            }

            currentFrontier = nextFrontier;
        }

        // Step 3: Build summary
        var allPropagated = waves.SelectMany(w => w.Nodes).ToList();
        var criticalPaths = allPropagated
            .Where(n => n.InheritedRisk >= 5.0)
            .Select(n => $"{n.ParentId} --[{n.RelationshipFromParent}]--> {n.Id} ({n.Label}) [Risk: {n.InheritedRisk:F1}]")
            .ToList();

        var summary = new PropagationSummary(
            TotalAffectedNodes: allPropagated.Count,
            CriticalNodes: allPropagated.Count(n => n.InheritedRisk >= 7.0),
            HighRiskNodes: allPropagated.Count(n => n.InheritedRisk >= 4.0 && n.InheritedRisk < 7.0),
            FacilitiesAffected: allPropagated.Count(n =>
                n.Type.Contains("Facility", StringComparison.OrdinalIgnoreCase) ||
                n.Type.Contains("Plant", StringComparison.OrdinalIgnoreCase) ||
                n.Type.Contains("Pump", StringComparison.OrdinalIgnoreCase) ||
                n.Type.Contains("Reservoir", StringComparison.OrdinalIgnoreCase)),
            PersonsAffected: allPropagated.Count(n =>
                n.Type.Contains("Person", StringComparison.OrdinalIgnoreCase) ||
                n.Type.Contains("Employee", StringComparison.OrdinalIgnoreCase) ||
                n.Type.Contains("Contractor", StringComparison.OrdinalIgnoreCase)),
            MaxPropagatedRisk: allPropagated.Count > 0 ? allPropagated.Max(n => n.InheritedRisk) : 0,
            CriticalPaths: criticalPaths.Take(10).ToList()
        );

        return new RiskPropagationResult(
            SourceNodeId: sourceNodeId,
            SourceLabel: sourceInfo.Label,
            SourceType: sourceInfo.Type,
            SourceRisk: sourceRisk,
            Waves: waves,
            Summary: summary,
            AffectedGraph: new GraphDto(allNodes, allEdges)
        );
    }

    // ═══════════════════════════════════════════════════════════════

    private async Task<NodeInfo?> GetNodeInfoAsync(string nodeId)
    {
        var cypher = @"
            MATCH (n)
            WHERE n.facilityId = $id OR n.eventId = $id OR n.personId = $id
               OR n.caseId = $id OR n.sensorId = $id OR n.assetId = $id
               OR n.organizationId = $id OR n.docId = $id
            RETURN labels(n) AS labels, properties(n) AS props,
                   n.name AS name, n.title AS title, n.facilityId AS fid,
                   n.personId AS pid, n.eventId AS eid, n.caseId AS cid,
                   n.description AS desc, n.riskScore AS risk
            LIMIT 1";

        var rows = await _repo.ExecuteCypherReadAsync(cypher, new Dictionary<string, object> { ["id"] = nodeId });
        if (rows.Count == 0) return null;

        var row = rows[0];
        var labels = row.GetValueOrDefault("labels", new List<object>()) as List<object> ?? [];
        var props = row.GetValueOrDefault("props", new Dictionary<string, object>()) as Dictionary<string, object> ?? [];
        var primaryLabel = labels.FirstOrDefault()?.ToString() ?? "Unknown";
        var name = row.GetValueOrDefault("name", null)?.ToString()
            ?? row.GetValueOrDefault("title", null)?.ToString()
            ?? row.GetValueOrDefault("desc", null)?.ToString()
            ?? nodeId;

        return new NodeInfo
        {
            Id = nodeId,
            Label = name,
            Type = primaryLabel,
            Properties = props,
            RiskScore = row.TryGetValue("risk", out var risk) && risk != null ? Convert.ToDouble(risk) : null
        };
    }

    private record NeighborInfo(string NodeId, string Label, string NodeType, string RelType, Dictionary<string, object> Properties);

    private async Task<List<NeighborInfo>> GetNeighborsAsync(string nodeId)
    {
        var cypher = @"
            MATCH (n)-[r]-(m)
            WHERE n.facilityId = $id OR n.eventId = $id OR n.personId = $id
               OR n.caseId = $id OR n.sensorId = $id OR n.assetId = $id
               OR n.organizationId = $id OR n.docId = $id
            RETURN type(r) AS relType, labels(m)[0] AS mType,
                   coalesce(m.facilityId, m.personId, m.eventId, m.caseId,
                            m.sensorId, m.assetId, m.organizationId, m.docId, toString(id(m))) AS mId,
                   coalesce(m.name, m.title, m.description, m.eventType, '') AS mLabel,
                   m.criticality AS crit, m.severity AS sev, m.riskScore AS risk
            LIMIT 50";

        var rows = await _repo.ExecuteCypherReadAsync(cypher, new Dictionary<string, object> { ["id"] = nodeId });
        var result = new List<NeighborInfo>();

        foreach (var row in rows)
        {
            var mId = row.GetValueOrDefault("mId", "")?.ToString();
            if (string.IsNullOrEmpty(mId)) continue;

            var props = new Dictionary<string, object>();
            if (row.TryGetValue("crit", out var c) && c != null) props["criticality"] = c;
            if (row.TryGetValue("sev", out var s) && s != null) props["severity"] = s;
            if (row.TryGetValue("risk", out var r) && r != null) props["riskScore"] = r;

            result.Add(new NeighborInfo(
                NodeId: mId,
                Label: row.GetValueOrDefault("mLabel", mId)?.ToString() ?? mId,
                NodeType: row.GetValueOrDefault("mType", "Unknown")?.ToString() ?? "Unknown",
                RelType: row.GetValueOrDefault("relType", "RELATED")?.ToString() ?? "RELATED",
                Properties: props
            ));
        }

        return result;
    }

    private static double DetermineSourceRisk(NodeInfo node)
    {
        if (node.RiskScore.HasValue) return node.RiskScore.Value;

        // Default risk by type
        return node.Type switch
        {
            "RiskCase" or "SuspectedSabotage" => 9.0,
            "Event" => node.Properties.TryGetValue("severity", out var s) ? Convert.ToDouble(s) * 2.0 : 6.0,
            "Facility" => node.Properties.TryGetValue("criticality", out var c) &&
                c?.ToString() == "HIGH" ? 8.0 : 5.0,
            "Person" => 7.0,
            _ => 5.0
        };
    }

    private static string CategorizeRisk(double risk) => risk switch
    {
        >= 7.0 => "critical",
        >= 5.0 => "high",
        >= 3.0 => "medium",
        >= 1.0 => "low",
        _ => "minimal"
    };

    private class NodeInfo
    {
        public string Id { get; set; } = "";
        public string Label { get; set; } = "";
        public string Type { get; set; } = "";
        public Dictionary<string, object> Properties { get; set; } = [];
        public double? RiskScore { get; set; }
    }
}
