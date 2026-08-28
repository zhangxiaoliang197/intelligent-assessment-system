namespace Aegis.Application.DTOs;

/// <summary>A single step in the agent's reasoning chain.</summary>
public record AgentStep(string Type, string Content);
// Type: "thought" | "action" | "observation" | "answer"
