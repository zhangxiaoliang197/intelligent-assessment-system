namespace Aegis.Domain.Entities;

public sealed class MilitaryEntityNode
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    /// <summary>Ontology class: ForceUnit / Equipment / Target.</summary>
    public required string OntologyType { get; init; }
    /// <summary>Operational role: reconnaissance / command / firepower / assessment / enemyTarget.</summary>
    public required string OperationalRole { get; init; }
    public required IReadOnlyDictionary<string, string> StaticProps { get; init; }
    public string Dataset { get; init; } = MilitaryDataset.DefaultDatasetId;
}

public sealed record MilitaryEntityRelation(
    string FromEntityId,
    string ToEntityId,
    string RelationType);

public sealed class MilitaryActionNode
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required int Sequence { get; init; }
    public required int TimeNode { get; init; }
    public required string Timestamp { get; init; }
    public required string Location { get; init; }
    public required string ActionType { get; init; }
    public required string ActionObject { get; init; }
    public required IReadOnlyList<string> PerformerEntityIds { get; init; }
    public required IReadOnlyList<string> TargetEntityIds { get; init; }
    public required IReadOnlyList<string> RecipientEntityIds { get; init; }
    public required string DirectResult { get; init; }
    /// <summary>Marks the action/effect used as the causal trace terminal for target destruction.</summary>
    public bool IsCausalTerminal { get; init; }
    public string Dataset { get; init; } = MilitaryDataset.DefaultDatasetId;
}

public sealed class MilitaryStateNode
{
    public required string Id { get; init; }
    public required string EntityId { get; init; }
    public required int Sequence { get; init; }
    public required string Timestamp { get; init; }
    public required string Location { get; init; }
    public required string Action { get; init; }
    public required string ActionObject { get; init; }
    public required string DirectResult { get; init; }
    public required string UpdatedState { get; init; }
    /// <summary>Source fidelity marker: explicit-record / joint-explicit-record / aggregate-unchanged-record / carried-forward / not-explicitly-recorded.</summary>
    public required string SourceBasis { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public string Dataset { get; init; } = MilitaryDataset.DefaultDatasetId;
}

public sealed record MilitaryCausalLink(string FromActionId, string ToActionId);

public sealed class MilitaryDataset
{
    public const string DefaultDatasetId = "military-causal-v5";

    public string Id { get; init; } = DefaultDatasetId;
    public required IReadOnlyList<MilitaryEntityNode> Entities { get; init; }
    public required IReadOnlyList<MilitaryEntityRelation> EntityRelations { get; init; }
    public required IReadOnlyList<MilitaryActionNode> Actions { get; init; }
    public required IReadOnlyList<MilitaryStateNode> States { get; init; }
    public required IReadOnlyList<MilitaryCausalLink> Causes { get; init; }
}

public sealed record MilitarySeedResult(
    string DatasetId,
    int EntityCount,
    int ActionCount,
    int StateCount,
    int RelationshipCount);

public sealed class CausalGraphNode
{
    public required string Id { get; init; }
    public required string Label { get; init; }
    public required string Type { get; init; }
    public string? Category { get; init; }
    public string? Role { get; init; }
    public IReadOnlyDictionary<string, object?> Properties { get; init; } = new Dictionary<string, object?>();
}

public sealed class CausalGraphEdge
{
    public required string Id { get; init; }
    public required string Source { get; init; }
    public required string Target { get; init; }
    public required string Type { get; init; }
    public IReadOnlyDictionary<string, object?> Properties { get; init; } = new Dictionary<string, object?>();
}

public sealed class CausalGraphResult
{
    public IReadOnlyList<CausalGraphNode> Nodes { get; init; } = [];
    public IReadOnlyList<CausalGraphEdge> Edges { get; init; } = [];
}

public sealed record EntityTimelinePoint(
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

public sealed record CausalStatistics(
    int EntityCount,
    int ActionCount,
    int StateCount,
    int RelationshipCount,
    int EntityTypeCount,
    int OperationalRoleCount,
    int RelationTypeCount,
    int CausalRelationCount);
