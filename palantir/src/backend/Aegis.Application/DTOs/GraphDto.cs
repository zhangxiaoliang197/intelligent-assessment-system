namespace Aegis.Application.DTOs;

public record GraphDto(
    List<GraphNodeDto> Nodes,
    List<GraphEdgeDto> Edges
);

public record GraphNodeDto(
    string Id,
    string Label,
    string Type,
    Dictionary<string, object> Properties
);

public record GraphEdgeDto(
    string Id,
    string Source,
    string Target,
    string Type,
    Dictionary<string, object> Properties
);

public record LinkAnalysisDto(
    List<DiscoveredPathDto> Paths,
    GraphDto Graph,
    int TotalPathsFound,
    string Summary
);

public record DiscoveredPathDto(
    string FromId,
    string FromLabel,
    string ToId,
    string ToLabel,
    int Length,
    List<string> NodeSequence,
    List<string> RelationshipSequence,
    double Relevance
);
