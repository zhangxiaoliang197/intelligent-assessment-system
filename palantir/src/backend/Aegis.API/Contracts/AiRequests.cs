namespace Aegis.API.Contracts;

/// <summary>Request body for follow-up chat on a risk case.</summary>
public record AiChatRequest(string Message, string? History);

/// <summary>Request body for entity investigation (facility, person, event).</summary>
public record InvestigateEntityRequest(string EntityType, string EntityId, string TimeRange);

/// <summary>Request body for entity follow-up chat.</summary>
public record ChatEntityRequest(string EntityType, string EntityId, string TimeRange, string Message, string? History);

/// <summary>Request body for agentic search.</summary>
public record AgenticSearchRequest(string Query);

/// <summary>Request body for Command Center NL→Cypher query.</summary>
public record CommandCenterRequest(string AgentId, string Query, string? History);
