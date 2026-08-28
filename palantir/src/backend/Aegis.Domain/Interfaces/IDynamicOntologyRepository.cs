using Aegis.Domain.Entities;

namespace Aegis.Domain.Interfaces;

public interface IDynamicOntologyRepository
{
    Task EnsureSchemaAsync(CancellationToken cancellationToken = default);
    Task<CausalGraphResult> GetDynamicGraphAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<OntologyRuleDescriptor>> GetRulesAsync(CancellationToken cancellationToken = default);
    Task<DynamicOntologyRunResult> RunDerivationRulesAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<ResolutionCandidate>> FindResolutionCandidatesAsync(CancellationToken cancellationToken = default);
    Task<OntologyMutation> MergeNodesAsync(MergeNodesRequest request, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<OntologyMutation>> GetMutationsAsync(int limit = 50, CancellationToken cancellationToken = default);
    Task<DynamicOntologyStatistics> GetStatisticsAsync(CancellationToken cancellationToken = default);
    Task<ManualOntologyNodeResult> CreateManualNodeAsync(ManualOntologyNodeRequest request, CancellationToken cancellationToken = default);
    Task<OntologyMutation> CreateManualRelationAsync(ManualOntologyRelationRequest request, CancellationToken cancellationToken = default);
    Task<OntologyAgentContext> BuildAgentContextAsync(CancellationToken cancellationToken = default);
    Task<OntologyProposal> SaveProposalAsync(OntologyProposal proposal, CancellationToken cancellationToken = default);
    Task<OntologyMutation> ApproveProposalAsync(string proposalId, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<OntologyProposal>> GetProposalsAsync(string? status = null, CancellationToken cancellationToken = default);
}
