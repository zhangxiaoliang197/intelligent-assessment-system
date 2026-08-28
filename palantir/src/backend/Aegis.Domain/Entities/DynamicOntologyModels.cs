namespace Aegis.Domain.Entities;

public static class OntologyOrigins
{
    public const string Asserted = "ASSERTED";
    public const string Rule = "RULE";
    public const string Agent = "AGENT";
    public const string Manual = "MANUAL";
}

public static class OntologyLifecycle
{
    public const string Active = "ACTIVE";
    public const string Merged = "MERGED";
    public const string Retired = "RETIRED";
}

public static class OntologyMutationTypes
{
    public const string NodeCreated = "NODE_CREATED";
    public const string NodeMerged = "NODE_MERGED";
    public const string ProposalCreated = "PROPOSAL_CREATED";
    public const string ProposalApproved = "PROPOSAL_APPROVED";
    public const string RelationCreated = "RELATION_CREATED";
}

public sealed record OntologyRuleDescriptor(
    string Id,
    string Name,
    string Description,
    string OutputType,
    bool Enabled,
    int Priority);

public sealed record OntologyMutation(
    string Id,
    string MutationType,
    DateTimeOffset ExecutedAt,
    string? RuleId,
    string? Reason,
    double Confidence,
    IReadOnlyList<string> SourceNodeIds,
    string? TargetNodeId,
    IReadOnlyDictionary<string, object?> Metadata);

public sealed record ResolutionCandidate(
    string LeftId,
    string LeftName,
    string RightId,
    string RightName,
    double Confidence,
    string Basis,
    string Recommendation);

public sealed record DynamicOntologyRunResult(
    int CreatedNodeCount,
    int MutationCount,
    IReadOnlyList<OntologyMutation> Mutations);

public sealed record DynamicOntologyStatistics(
    int AssertedNodeCount,
    int DerivedNodeCount,
    int ActiveNodeCount,
    int RuleCount,
    int PendingResolutionCount,
    int PendingProposalCount,
    int MutationCount);

public sealed class ManualOntologyNodeRequest
{
    public required string Name { get; init; }
    public required string OntologyType { get; init; }
    public required string OperationalRole { get; init; }
    public string? CanonicalKey { get; init; }
    public Dictionary<string, string> Properties { get; init; } = new();
}

public sealed class ManualOntologyRelationRequest
{
    public required string SourceId { get; init; }
    public required string TargetId { get; init; }
    public required string RelationType { get; init; }
    public Dictionary<string, string> Properties { get; init; } = new();
}

public sealed record ManualOntologyNodeResult(string Id, string Name, string OntologyType);

public sealed class MergeNodesRequest
{
    public required string SourceNodeId { get; init; }
    public required string TargetNodeId { get; init; }
    public string Reason { get; init; } = "Entity resolution confirmed";
    public double Confidence { get; init; } = 1.0;
    public bool PhysicalMerge { get; init; } = true;
}

public sealed class OntologyAgentRequest
{
    public string Focus { get; init; } = "请识别当前图谱中现有本体无法充分表达的潜在新概念、关系或规则。";
}

public sealed class OntologyProposal
{
    public required string Id { get; init; }
    public required string ProposalType { get; init; }
    public required string Name { get; init; }
    public string? ParentClass { get; init; }
    public required string Description { get; init; }
    public double Confidence { get; init; }
    public IReadOnlyList<string> Evidence { get; init; } = [];
    public string Status { get; init; } = "PROPOSED";
    public DateTimeOffset CreatedAt { get; init; } = DateTimeOffset.UtcNow;
}

public sealed record OntologyAgentContext(
    IReadOnlyList<string> NodeTypes,
    IReadOnlyList<string> RelationshipTypes,
    IReadOnlyList<string> EntitySamples,
    IReadOnlyList<string> DerivedSamples,
    IReadOnlyList<string> ExistingRules);
