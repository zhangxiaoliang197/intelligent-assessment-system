namespace Aegis.Application.DTOs;

// ── Multi-Agent Command Center ──

public record AgentProfile(
    string Id,
    string Name,
    string Role,
    string Description,
    string Icon,     // emoji
    string Color     // tailwind color name
);

public record CommandCenterResponse(
    string AgentId,
    string AgentName,
    string OriginalQuery,
    string? GeneratedCypher,
    string? CypherExplanation,
    List<Dictionary<string, object>>? QueryResults,
    string Analysis,
    AlertAction? Alert
);

public record AlertAction(
    string Type,          // "notify_person" | "alert_facility" | "escalate_case" | "broadcast"
    string Target,        // Entity ID or name
    string Message,       // Alert message
    string Severity,      // "info" | "warning" | "critical"
    string Timestamp
);

// ── Risk Propagation ──

public record RiskPropagationRequest(
    string SourceNodeId,
    int MaxDepth = 5,
    double DecayFactor = 0.6
);

public record RiskPropagationResult(
    string SourceNodeId,
    string SourceLabel,
    string SourceType,
    double SourceRisk,
    List<PropagationWave> Waves,
    PropagationSummary Summary,
    GraphDto AffectedGraph
);

public record PropagationWave(
    int Depth,
    double RiskLevel,
    string RiskCategory,      // "critical" | "high" | "medium" | "low" | "minimal"
    List<PropagatedNode> Nodes
);

public record PropagatedNode(
    string Id,
    string Label,
    string Type,
    double InheritedRisk,
    string RelationshipFromParent,
    string ParentId,
    Dictionary<string, object> Properties
);

public record PropagationSummary(
    int TotalAffectedNodes,
    int CriticalNodes,
    int HighRiskNodes,
    int FacilitiesAffected,
    int PersonsAffected,
    double MaxPropagatedRisk,
    List<string> CriticalPaths
);
