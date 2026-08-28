using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.API.Contracts;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

/// <summary>
/// AI Agent investigation endpoints.  Streams ReAct agent reasoning steps
/// (Thought → Action → Observation → Answer) via SSE.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class AiController(
    IAegisService aegis,
    IAgentService agent,
    ILogger<AiController> logger,
    IConfiguration configuration) : ControllerBase
{
    [HttpGet("status")]
    public ActionResult AiStatus()
    {
        var apiKey = configuration["DeepSeek:ApiKey"] ?? configuration["DEEPSEEK_API_KEY"];
        var baseUrl = configuration["DeepSeek:BaseUrl"] ??
                      configuration["DEEPSEEK_BASE_URL"] ??
                      "https://api.deepseek.com";
        var model = configuration["DeepSeek:Model"] ??
                    configuration["DEEPSEEK_MODEL"] ??
                    "deepseek-chat";

        return Ok(new
        {
            provider = "DeepSeek",
            configured = !string.IsNullOrWhiteSpace(apiKey),
            baseUrl,
            model
        });
    }

    [HttpPost("investigate/{caseId}")]
    public async Task Investigate(string caseId)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            var cases = await aegis.GetRiskCasesAsync(HttpContext.RequestAborted);
            var riskCase = cases.FirstOrDefault(c => c.CaseId == caseId);
            if (riskCase == null)
            {
                await WriteSseStepAsync("answer", "[ERROR] Risk case not found");
                await WriteSseAsync("data: [DONE]\n\n");
                return;
            }

            var graph = await aegis.GetCaseGraphAsync(caseId, HttpContext.RequestAborted);
            var caseContext = BuildCaseContext(riskCase, graph);

            await foreach (var step in agent.InvestigateAsync(caseId, caseContext, HttpContext.RequestAborted))
            {
                await WriteSseStepAsync(step.Type, step.Content);
            }

            await WriteSseAsync("data: [DONE]\n\n");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Agent investigation failed for case {CaseId}", caseId);
            await WriteSseStepAsync("answer", $"[ERROR] {ex.Message}");
            await WriteSseAsync("data: [DONE]\n\n");
        }
    }

    [HttpPost("chat/{caseId}")]
    public async Task Chat(string caseId, [FromBody] AiChatRequest request)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            var cases = await aegis.GetRiskCasesAsync(HttpContext.RequestAborted);
            var riskCase = cases.FirstOrDefault(c => c.CaseId == caseId);

            var caseContext = riskCase != null
                ? $"Risk case: {riskCase.Title} (Risk {riskCase.RiskScore:F1}/10) at {riskCase.FacilityName ?? "unknown"}. {riskCase.Description}. Linked events: {riskCase.LinkedEventsCount}. Persons: {string.Join(", ", riskCase.LinkedPersonNames)}"
                : $"Risk case {caseId}";

            await foreach (var step in agent.ChatAsync(caseId, caseContext, request.Message, request.History, HttpContext.RequestAborted))
            {
                await WriteSseStepAsync(step.Type, step.Content);
            }

            await WriteSseAsync("data: [DONE]\n\n");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Agent chat failed for case {CaseId}", caseId);
            await WriteSseStepAsync("answer", $"[ERROR] {ex.Message}");
            await WriteSseAsync("data: [DONE]\n\n");
        }
    }

    [HttpPost("investigate-entity")]
    public async Task InvestigateEntity([FromBody] InvestigateEntityRequest request)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            await foreach (var step in agent.InvestigateEntityAsync(
                request.EntityType, request.EntityId, request.TimeRange, HttpContext.RequestAborted))
            {
                await WriteSseStepAsync(step.Type, step.Content);
            }

            await WriteSseAsync("data: [DONE]\n\n");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Entity investigation failed for {Type}/{Id}", request.EntityType, request.EntityId);
            await WriteSseStepAsync("answer", $"[ERROR] {ex.Message}");
            await WriteSseAsync("data: [DONE]\n\n");
        }
    }

    [HttpPost("chat-entity")]
    public async Task ChatEntity([FromBody] ChatEntityRequest request)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            var entityContext = $"{request.EntityType} {request.EntityId} (time window: {request.TimeRange})";
            await foreach (var step in agent.ChatAsync(
                request.EntityId, entityContext, request.Message, request.History, HttpContext.RequestAborted))
            {
                await WriteSseStepAsync(step.Type, step.Content);
            }

            await WriteSseAsync("data: [DONE]\n\n");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Entity chat failed for {Type}/{Id}", request.EntityType, request.EntityId);
            await WriteSseStepAsync("answer", $"[ERROR] {ex.Message}");
            await WriteSseAsync("data: [DONE]\n\n");
        }
    }

    [HttpPost("agentic-search")]
    public async Task AgenticSearch([FromBody] AgenticSearchRequest request)
    {
        Response.ContentType = "text/event-stream";
        Response.Headers.CacheControl = "no-cache";
        Response.Headers.Connection = "keep-alive";

        try
        {
            var searchResult = await aegis.SearchAsync(request.Query, 1, 30, HttpContext.RequestAborted);

            await foreach (var step in agent.AgenticSearchAsync(
                request.Query, searchResult, HttpContext.RequestAborted))
            {
                await WriteSseStepAsync(step.Type, step.Content);
            }

            await WriteSseAsync("data: [DONE]\n\n");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            logger.LogError(ex, "Agentic search failed for query '{Query}'", request.Query);
            await WriteSseStepAsync("answer", $"[ERROR] {ex.Message}");
            await WriteSseAsync("data: [DONE]\n\n");
        }
    }

    // ── Private helpers ──

    private static string BuildCaseContext(RiskCaseDto riskCase, GraphDto graph)
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"## Risk Case: {riskCase.Title}");
        sb.AppendLine($"- Case ID: {riskCase.CaseId}");
        sb.AppendLine($"- Status: {riskCase.Status}");
        sb.AppendLine($"- Risk Score: {riskCase.RiskScore:F1}/10");
        sb.AppendLine($"- Confidence: {riskCase.Confidence:P0}");
        sb.AppendLine($"- Facility: {riskCase.FacilityName ?? "Multiple"}");
        sb.AppendLine($"- Created: {riskCase.CreatedAt:u}");
        sb.AppendLine($"- Description: {riskCase.Description}");
        sb.AppendLine($"- Linked Events: {riskCase.LinkedEventsCount}");
        if (riskCase.LinkedPersonNames.Count > 0)
            sb.AppendLine($"- Persons Involved: {string.Join(", ", riskCase.LinkedPersonNames)}");

        sb.AppendLine("\n### Key entities in the knowledge graph (partial view):");
        foreach (var node in graph.Nodes.Take(15))
            sb.AppendLine($"- [{node.Type}] {node.Label}");

        sb.AppendLine($"\n### Relationships ({graph.Edges.Count} total):");
        foreach (var edge in graph.Edges.Take(15))
        {
            var src = graph.Nodes.FirstOrDefault(n => n.Id == edge.Source)?.Label ?? edge.Source;
            var tgt = graph.Nodes.FirstOrDefault(n => n.Id == edge.Target)?.Label ?? edge.Target;
            sb.AppendLine($"- {src} --[{edge.Type}]--> {tgt}");
        }

        sb.AppendLine("\nYou can use your tools to explore the full graph deeply. Start by querying the ontology schema.");
        return sb.ToString();
    }

    private async Task WriteSseStepAsync(string type, string content)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(new { type, content });
        await Response.WriteAsync($"data: {json}\n\n", HttpContext.RequestAborted);
        await Response.Body.FlushAsync(HttpContext.RequestAborted);
    }

    private async Task WriteSseAsync(string data)
    {
        await Response.WriteAsync(data, HttpContext.RequestAborted);
        await Response.Body.FlushAsync(HttpContext.RequestAborted);
    }
}
