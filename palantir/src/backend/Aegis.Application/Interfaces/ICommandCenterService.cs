using Aegis.Application.DTOs;

namespace Aegis.Application.Interfaces;

/// <summary>
/// Multi-agent Command Center service.
/// Orchestrates specialized AI agents with different profiles (military, civil, operations)
/// that translate natural language into Cypher queries and actionable intelligence.
/// </summary>
public interface ICommandCenterService
{
    /// <summary>Returns all available agent profiles.</summary>
    List<AgentProfile> GetAgentProfiles();

    /// <summary>
    /// Process a natural language query through a specific agent profile.
    /// The agent translates NL → Cypher, executes, and provides domain-specific analysis.
    /// Streams steps via SSE (thought → cypher → observation → answer).
    /// </summary>
    IAsyncEnumerable<AgentStep> QueryAsync(
        string agentId,
        string naturalLanguageQuery,
        string? conversationHistory,
        CancellationToken ct);
}

/// <summary>
/// Risk propagation engine — calculates blast radius from a compromised node
/// through graph relationships with exponential decay.
/// </summary>
public interface IRiskPropagationService
{
    /// <summary>
    /// Calculate risk propagation waves from a source node.
    /// Each wave represents a depth level with decayed risk scores.
    /// </summary>
    Task<RiskPropagationResult> PropagateRiskAsync(
        string sourceNodeId,
        int maxDepth = 5,
        double decayFactor = 0.6,
        CancellationToken ct = default);
}
