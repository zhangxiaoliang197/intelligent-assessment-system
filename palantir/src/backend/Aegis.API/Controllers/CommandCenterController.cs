using System.Text.Json;
using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.API.Contracts;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

static file class CommandCenterJsonOptions
{
    public static readonly JsonSerializerOptions CamelCase = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };
}

/// <summary>
/// Multi-Agent Command Center — NL → Cypher → Intelligence Analysis.
/// Multiple specialized agents (Military, Civil, Operations, Sentinel) interpret
/// natural language queries, translate to Cypher, and provide domain-specific analysis.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class CommandCenterController(
    ICommandCenterService commandCenter,
    ILogger<CommandCenterController> logger) : ControllerBase
{
    /// <summary>Get all available agent profiles.</summary>
    [HttpGet("agents")]
    [ProducesResponseType<List<AgentProfile>>(200)]
    public IActionResult GetAgents() => Ok(commandCenter.GetAgentProfiles());

    /// <summary>
    /// Send a natural language query to a specific agent.
    /// Streams SSE: agent → thought → cypher → observation → alert? → answer.
    /// </summary>
    [HttpPost("query")]
    public async Task Query([FromBody] CommandCenterRequest request)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            await foreach (var step in commandCenter.QueryAsync(
                request.AgentId, request.Query, request.History, HttpContext.RequestAborted))
            {
                var json = JsonSerializer.Serialize(new { step.Type, step.Content }, CommandCenterJsonOptions.CamelCase);
                await Response.WriteAsync($"data: {json}\n\n", HttpContext.RequestAborted);
                await Response.Body.FlushAsync(HttpContext.RequestAborted);
            }

            await Response.WriteAsync("data: [DONE]\n\n", HttpContext.RequestAborted);
            await Response.Body.FlushAsync(HttpContext.RequestAborted);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Command center query failed for agent {AgentId}", request.AgentId);
            var error = JsonSerializer.Serialize(new { type = "answer", content = $"[ERROR] {ex.Message}" }, CommandCenterJsonOptions.CamelCase);
            await Response.WriteAsync($"data: {error}\n\n", HttpContext.RequestAborted);
            await Response.WriteAsync("data: [DONE]\n\n", HttpContext.RequestAborted);
            await Response.Body.FlushAsync(HttpContext.RequestAborted);
        }
    }
}
