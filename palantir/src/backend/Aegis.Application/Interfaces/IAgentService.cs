using Aegis.Application.DTOs;

namespace Aegis.Application.Interfaces;

/// <summary>
/// ReAct (Reasoning + Acting) AI agent that investigates risk cases, entities,
/// and performs agentic search by autonomously querying the knowledge graph.
/// </summary>
public interface IAgentService
{
    /// <summary>
    /// Run the ReAct agent loop for a risk case investigation.
    /// Yields reasoning steps (thought → action → observation → answer).
    /// </summary>
    IAsyncEnumerable<AgentStep> InvestigateAsync(
        string caseId, string caseContext, CancellationToken ct);

    /// <summary>
    /// Follow-up chat that uses the agent (can query the graph for answers).
    /// </summary>
    IAsyncEnumerable<AgentStep> ChatAsync(
        string caseId, string caseContext, string message, string? history, CancellationToken ct);

    /// <summary>
    /// Investigate any entity (facility, person, event) with a time-scoped window.
    /// </summary>
    IAsyncEnumerable<AgentStep> InvestigateEntityAsync(
        string entityType, string entityId, string timeRange, CancellationToken ct);

    /// <summary>
    /// AI-powered search: takes Elasticsearch results and generates intelligent insights.
    /// </summary>
    IAsyncEnumerable<AgentStep> AgenticSearchAsync(
        string userQuery, SearchResultDto searchResults, CancellationToken ct);
}
