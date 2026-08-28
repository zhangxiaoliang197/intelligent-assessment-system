using Aegis.Domain.Entities;

namespace Aegis.API.Contracts;

public sealed record CausalGraphNodeDto(
    string Id,
    string Label,
    string Type,
    string? Category,
    string? Role,
    IReadOnlyDictionary<string, object?> Properties);

public sealed record CausalGraphEdgeDto(
    string Id,
    string Source,
    string Target,
    string Type,
    IReadOnlyDictionary<string, object?> Properties);

public sealed record CausalGraphDto(
    IReadOnlyList<CausalGraphNodeDto> Nodes,
    IReadOnlyList<CausalGraphEdgeDto> Edges);

public sealed record EntityTimelinePointDto(
    string Timestamp,
    string Location,
    string Action,
    string ActionObject,
    string DirectResult,
    string UpdatedState,
    string SourceBasis,
    int Sequence,
    double? Latitude,
    double? Longitude);

public sealed record CausalStatisticsDto(
    int EntityCount,
    int ActionCount,
    int StateCount,
    int RelationshipCount,
    int EntityTypeCount,
    int OperationalRoleCount,
    int RelationTypeCount,
    int CausalRelationCount);

public sealed record MilitarySeedResponseDto(
    string DatasetId,
    int Entities,
    int Actions,
    int States,
    int Relationships,
    int SearchDocuments,
    string Message);

public sealed class CausalAttributionRequest
{
    public required string TargetEntityId { get; init; }
    public int MaxDepth { get; init; } = 12;
    public bool IncludeCounterfactual { get; init; } = true;
}

public sealed record CausalAttributionSummaryDto(
    int ActionCount,
    int EntityCount,
    int PhaseCount,
    int PathCount,
    int CriticalNodeCount);

public sealed record CausalAttributionItemDto(
    string Id,
    string Name,
    string? Type,
    string? Phase,
    double ContributionPercent,
    double CounterfactualImpactPercent,
    int PathCount,
    bool Direct);

public sealed record CausalAttributionPathDto(
    IReadOnlyList<string> NodeIds,
    IReadOnlyList<string> NodeNames,
    double Weight);

public sealed record CausalCounterfactualDto(
    string NodeId,
    string NodeName,
    double ImpactPercent,
    bool OnEveryPath);

public sealed record CausalAttributionDto(
    CausalGraphNodeDto Target,
    CausalAttributionSummaryDto Summary,
    IReadOnlyList<CausalAttributionItemDto> Actions,
    IReadOnlyList<CausalAttributionItemDto> Entities,
    IReadOnlyList<CausalAttributionItemDto> Phases,
    IReadOnlyList<CausalAttributionPathDto> Paths,
    IReadOnlyList<CausalCounterfactualDto> CriticalNodes);

public static class CausalDtoMapper
{
    public static CausalGraphDto ToDto(this CausalGraphResult result) => new(
        result.Nodes.Select(n => new CausalGraphNodeDto(n.Id, n.Label, n.Type, n.Category, n.Role, n.Properties)).ToArray(),
        result.Edges.Select(e => new CausalGraphEdgeDto(e.Id, e.Source, e.Target, e.Type, e.Properties)).ToArray());

    public static EntityTimelinePointDto ToDto(this EntityTimelinePoint point) =>
        new(point.Timestamp, point.Location, point.Action, point.ActionObject, point.DirectResult,
            point.UpdatedState, point.SourceBasis, point.Sequence, point.Latitude, point.Longitude);

    public static CausalStatisticsDto ToDto(this CausalStatistics stats) => new(
        stats.EntityCount,
        stats.ActionCount,
        stats.StateCount,
        stats.RelationshipCount,
        stats.EntityTypeCount,
        stats.OperationalRoleCount,
        stats.RelationTypeCount,
        stats.CausalRelationCount);
}
