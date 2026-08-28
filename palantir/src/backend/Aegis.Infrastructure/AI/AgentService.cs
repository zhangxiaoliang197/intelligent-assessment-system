using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Runtime.CompilerServices;
using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Aegis.Infrastructure.AI;

/// <summary>
/// ReAct (Reasoning + Acting) agent that investigates risk cases by iteratively
/// thinking, selecting tools, executing them against the Neo4j knowledge graph,
/// observing results, and reasoning further.
///
/// This is NOT prompt engineering — the agent autonomously decides which Cypher
/// queries to run, which parts of the ontology to explore, and how to interpret
/// the results.  The ontology structure drives the reasoning, not if/then/else.
/// </summary>
public sealed class AgentService : IAgentService
{
    private readonly IOllamaService _ollama;
    private readonly IServiceProvider _services;
    private readonly ILogger<AgentService> _logger;
    private const int MaxIterations = 8;

    public AgentService(
        IOllamaService ollama,
        IServiceProvider services,
        ILogger<AgentService> logger)
    {
        _ollama = ollama;
        _services = services;
        _logger = logger;
    }

    // ═══════════════════════════════════════════════════════════════
    //  TOOL DEFINITIONS — The agent discovers the graph, it doesn't
    //  use hardcoded logic.  It writes Cypher queries dynamically.
    // ═══════════════════════════════════════════════════════════════

    private static readonly string ToolDescriptions = """
        You have these tools available.  To use a tool, respond EXACTLY in this format:

        Action: <tool_name>
        Action Input: <input>

        Available tools:

        1. query_graph
           Execute a read-only Cypher query against the Neo4j knowledge graph.
           Input: A valid Cypher MATCH/RETURN query.  Always use LIMIT to avoid huge results.
           Example Action Input: MATCH (e:Event)-[:OCCURRED_AT]->(f:Facility) WHERE f.facilityId = 'FAC-001' RETURN e.eventType, e.severity, e.description LIMIT 10

        2. get_ontology
           Get the full ontology schema: all node types, their properties, relationship types,
           and how nodes connect.  Use this FIRST to understand the data model before querying.
           Input: (none needed, just write "get_ontology")

        3. get_node_neighbors
           Get all nodes and relationships directly connected to a specific node.
           Input: The node ID (e.g., FAC-001, PER-003, EVT-xxx, CASE-xxx)

        4. search_events
           Search events by type, severity, and/or time range at a specific facility.
           Input: JSON object like {"facilityId": "FAC-001", "eventType": "CyberAlert", "minSeverity": 3, "from": "2026-02-26T00:00:00Z", "to": "2026-02-27T23:59:59Z"}
           The "from" and "to" fields are optional ISO 8601 dates to filter by time window.

        5. get_risk_patterns
           Analyze temporal and relational patterns for a facility: event frequency,
           severity trends, person involvement, relationship density.
           Input: The facility ID (e.g., FAC-001)

        When you have enough information to provide a complete analysis, respond with:
        Final Answer: <your complete investigation report in Markdown>

        IMPORTANT RULES:
        - ALWAYS start by calling get_ontology to understand the graph structure
        - Use query_graph with Cypher to explore relationships the other tools don't cover
        - Reason about WHY patterns exist based on the ontology relationships
        - Never guess — always query the graph to verify hypotheses
        - Think step by step, explain your reasoning at each step
        - Respond in the same language the user writes to you
        """;

    // ═══════════════════════════════════════════════════════════════
    //  REACT LOOP
    // ═══════════════════════════════════════════════════════════════

    /// <inheritdoc />
    public async IAsyncEnumerable<AgentStep> InvestigateAsync(
        string caseId, string caseContext, [EnumeratorCancellation] CancellationToken ct)
    {
        var scratchpad = new StringBuilder();
        scratchpad.AppendLine($"Task: Investigate this risk case thoroughly.\n\n{caseContext}");

        for (int i = 0; i < MaxIterations && !ct.IsCancellationRequested; i++)
        {
            _logger.LogDebug("Agent iteration {Iter} for case {CaseId}", i + 1, caseId);

            var systemPrompt = BuildSystemPrompt();
            var userPrompt = scratchpad + "\n\nNow think step-by-step about what to do next. " +
                "Either use a tool or provide your Final Answer.";

            var response = await _ollama.GenerateAsync(systemPrompt, userPrompt, ct);
            var parsed = ParseAgentResponse(response);

            if (parsed.Thought != null)
            {
                yield return new AgentStep("thought", parsed.Thought);
                scratchpad.AppendLine($"\nThought: {parsed.Thought}");
            }

            if (parsed.FinalAnswer != null)
            {
                yield return new AgentStep("answer", parsed.FinalAnswer);
                yield break;
            }

            if (parsed.Action != null && parsed.ActionInput != null)
            {
                yield return new AgentStep("action", $"🔧 {parsed.Action}: {parsed.ActionInput}");

                var observation = await ExecuteToolAsync(parsed.Action, parsed.ActionInput, ct);
                if (observation.Length > 3000)
                    observation = observation[..3000] + "\n... (truncated)";

                yield return new AgentStep("observation", observation);

                scratchpad.AppendLine($"\nAction: {parsed.Action}");
                scratchpad.AppendLine($"Action Input: {parsed.ActionInput}");
                scratchpad.AppendLine($"Observation: {observation}");
            }
            else if (parsed.FinalAnswer == null)
            {
                scratchpad.AppendLine($"\nThought: {response}");
                scratchpad.AppendLine("\nReminder: You MUST use a tool (Action/Action Input) or provide a Final Answer.");
            }
        }

        var finalPrompt = scratchpad +
            "\n\nYou have reached the maximum number of investigation steps. " +
            "Based on everything you've discovered, provide your Final Answer now.";

        var finalResponse = await _ollama.GenerateAsync(BuildSystemPrompt(), finalPrompt, ct);
        var finalParsed = ParseAgentResponse(finalResponse);
        yield return new AgentStep("answer", finalParsed.FinalAnswer ?? finalResponse);
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<AgentStep> ChatAsync(
        string caseId, string caseContext, string message, string? history,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var scratchpad = new StringBuilder();
        scratchpad.AppendLine($"Context: {caseContext}");
        if (!string.IsNullOrEmpty(history))
            scratchpad.AppendLine($"\nPrevious conversation:\n{history}");
        scratchpad.AppendLine($"\nUser question: {message}");

        for (int i = 0; i < 5 && !ct.IsCancellationRequested; i++)
        {
            var response = await _ollama.GenerateAsync(BuildSystemPrompt(), scratchpad.ToString(), ct);
            var parsed = ParseAgentResponse(response);

            if (parsed.Thought != null)
            {
                yield return new AgentStep("thought", parsed.Thought);
                scratchpad.AppendLine($"\nThought: {parsed.Thought}");
            }

            if (parsed.FinalAnswer != null)
            {
                yield return new AgentStep("answer", parsed.FinalAnswer);
                yield break;
            }

            if (parsed.Action != null && parsed.ActionInput != null)
            {
                yield return new AgentStep("action", $"🔧 {parsed.Action}: {parsed.ActionInput}");
                var observation = await ExecuteToolAsync(parsed.Action, parsed.ActionInput, ct);
                if (observation.Length > 2000) observation = observation[..2000] + "\n...";
                yield return new AgentStep("observation", observation);
                scratchpad.AppendLine($"\nAction: {parsed.Action}");
                scratchpad.AppendLine($"Action Input: {parsed.ActionInput}");
                scratchpad.AppendLine($"Observation: {observation}");
            }
            else
            {
                yield return new AgentStep("answer", response);
                yield break;
            }
        }

        yield return new AgentStep("answer", "I've completed my analysis based on the available data.");
    }

    // ═══════════════════════════════════════════════════════════════
    //  TOOL EXECUTION
    // ═══════════════════════════════════════════════════════════════

    private async Task<string> ExecuteToolAsync(string toolName, string input, CancellationToken ct)
    {
        using var scope = _services.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<IGraphRepository>();

        try
        {
            return toolName.Trim().ToLowerInvariant() switch
            {
                "query_graph" => await ExecuteCypherToolAsync(repo, input, ct),
                "get_ontology" => await repo.GetOntologySchemaAsync(),
                "get_node_neighbors" => await GetNodeNeighborsAsync(repo, input.Trim(), ct),
                "search_events" => await SearchEventsToolAsync(repo, input, ct),
                "get_risk_patterns" => await AnalyzePatternsAsync(repo, input.Trim(), ct),
                _ => $"Unknown tool: {toolName}. Available: query_graph, get_ontology, get_node_neighbors, search_events, get_risk_patterns"
            };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Agent tool '{Tool}' failed", toolName);
            return $"Tool error: {ex.Message}";
        }
    }

    private static async Task<string> ExecuteCypherToolAsync(IGraphRepository repo, string cypher, CancellationToken ct)
    {
        var normalized = cypher.Trim().ToUpperInvariant();
        if (normalized.Contains("DELETE") || normalized.Contains("DETACH") ||
            normalized.Contains("CREATE") || normalized.Contains("MERGE") ||
            normalized.Contains("SET ") || normalized.Contains("REMOVE"))
        {
            return "ERROR: Only read-only Cypher queries (MATCH/RETURN) are allowed.";
        }

        if (!normalized.Contains("LIMIT"))
            cypher += " LIMIT 25";

        var rows = await repo.ExecuteCypherReadAsync(cypher);
        if (rows.Count == 0) return "No results found.";

        var sb = new StringBuilder();
        sb.AppendLine($"Results ({rows.Count} rows):");
        foreach (var row in rows.Take(25))
        {
            var parts = row.Select(kvp =>
                $"{kvp.Key}: {FormatValue(kvp.Value)}");
            sb.AppendLine("  " + string.Join(" | ", parts));
        }
        return sb.ToString();
    }

    private static async Task<string> GetNodeNeighborsAsync(IGraphRepository repo, string nodeId, CancellationToken ct)
    {
        var cypher = @"
            MATCH (n)-[r]-(m)
            WHERE n.facilityId = $id OR n.eventId = $id OR n.personId = $id
               OR n.caseId = $id OR n.sensorId = $id OR n.assetId = $id
               OR n.organizationId = $id
            RETURN labels(n)[0] AS sourceType, n AS source,
                   type(r) AS relationship, 
                   labels(m)[0] AS targetType, m AS target
            LIMIT 30";

        var rows = await repo.ExecuteCypherReadAsync(cypher, new Dictionary<string, object> { ["id"] = nodeId });
        if (rows.Count == 0) return $"No node found with ID '{nodeId}'.";

        var sb = new StringBuilder();
        sb.AppendLine($"Neighbors of {nodeId} ({rows.Count} connections):");
        foreach (var row in rows)
        {
            var rel = row.GetValueOrDefault("relationship", "?");
            var targetType = row.GetValueOrDefault("targetType", "?");
            var target = row.GetValueOrDefault("target", new Dictionary<string, object>());
            var targetProps = target is Dictionary<string, object> dict
                ? string.Join(", ", dict.Take(4).Select(k => $"{k.Key}={k.Value}"))
                : target?.ToString() ?? "";
            sb.AppendLine($"  -[{rel}]-> ({targetType}) {targetProps}");
        }
        return sb.ToString();
    }

    private static async Task<string> SearchEventsToolAsync(IGraphRepository repo, string input, CancellationToken ct)
    {
        var filter = new EventFilter();
        try
        {
            using var doc = JsonDocument.Parse(input);
            var root = doc.RootElement;
            if (root.TryGetProperty("facilityId", out var fid)) filter.FacilityId = fid.GetString();
            if (root.TryGetProperty("eventType", out var et)) filter.EventType = et.GetString();
            if (root.TryGetProperty("minSeverity", out var ms)) filter.MinSeverity = ms.GetInt32();
            if (root.TryGetProperty("severity", out var s)) filter.Severity = s.GetInt32();
            if (root.TryGetProperty("from", out var fromP) && DateTime.TryParse(fromP.GetString(), out var fromDt)) filter.From = fromDt;
            if (root.TryGetProperty("to", out var toP) && DateTime.TryParse(toP.GetString(), out var toDt)) filter.To = toDt;
        }
        catch
        {
            filter.FacilityId = input.Trim();
        }

        var events = (await repo.GetEventsAsync(filter)).Take(20).ToList();
        if (events.Count == 0) return "No events match the filter.";

        var sb = new StringBuilder();
        sb.AppendLine($"Found {events.Count} events:");
        foreach (var e in events)
        {
            sb.AppendLine($"  [{e.EventType}] SEV-{e.Severity} at {e.FacilityName ?? e.FacilityId} ({e.Timestamp:u})");
            sb.AppendLine($"    {e.Description}");
            if (e.PersonName != null) sb.AppendLine($"    Person: {e.PersonName}");
        }
        return sb.ToString();
    }

    private static async Task<string> AnalyzePatternsAsync(IGraphRepository repo, string facilityId, CancellationToken ct)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"Pattern analysis for {facilityId}:\n");

        var typeDistro = await repo.ExecuteCypherReadAsync(@"
            MATCH (e:Event)-[:OCCURRED_AT]->(f:Facility {facilityId: $fid})
            RETURN e.eventType AS type, count(*) AS count, avg(e.severity) AS avgSev
            ORDER BY count DESC",
            new Dictionary<string, object> { ["fid"] = facilityId });

        sb.AppendLine("## Event Distribution:");
        foreach (var r in typeDistro)
            sb.AppendLine($"  {r["type"]}: {r["count"]} events (avg severity {r.GetValueOrDefault("avgSev", 0):F1})");

        var persons = await repo.ExecuteCypherReadAsync(@"
            MATCH (p:Person)-[:INVOLVED_IN]->(e:Event)-[:OCCURRED_AT]->(f:Facility {facilityId: $fid})
            WHERE e.severity >= 2
            RETURN p.name AS name, p.personType AS type, count(e) AS eventCount,
                   max(e.severity) AS maxSev, collect(DISTINCT e.eventType) AS eventTypes
            ORDER BY eventCount DESC LIMIT 10",
            new Dictionary<string, object> { ["fid"] = facilityId });

        sb.AppendLine("\n## Person Involvement (severity >= 2):");
        foreach (var r in persons)
            sb.AppendLine($"  {r["name"]} ({r["type"]}): {r["eventCount"]} events, max SEV-{r["maxSev"]}, types: {FormatValue(r.GetValueOrDefault("eventTypes", "?"))}");

        var cases = await repo.ExecuteCypherReadAsync(@"
            MATCH (rc:RiskCase)-[:LINKED_TO]->(e:Event)-[:OCCURRED_AT]->(f:Facility {facilityId: $fid})
            RETURN DISTINCT rc.caseId AS caseId, rc.title AS title, rc.riskScore AS riskScore, rc.status AS status
            ORDER BY rc.riskScore DESC",
            new Dictionary<string, object> { ["fid"] = facilityId });

        sb.AppendLine("\n## Related Risk Cases:");
        foreach (var r in cases)
            sb.AppendLine($"  {r["caseId"]}: {r["title"]} (Risk: {r["riskScore"]}, Status: {r["status"]})");

        var density = await repo.ExecuteCypherReadAsync(@"
            MATCH (f:Facility {facilityId: $fid})-[r]-()
            RETURN type(r) AS relType, count(*) AS count ORDER BY count DESC",
            new Dictionary<string, object> { ["fid"] = facilityId });

        sb.AppendLine("\n## Relationship Density:");
        foreach (var r in density)
            sb.AppendLine($"  {r["relType"]}: {r["count"]} connections");

        return sb.ToString();
    }

    // ═══════════════════════════════════════════════════════════════
    //  ENTITY INVESTIGATION
    // ═══════════════════════════════════════════════════════════════

    /// <inheritdoc />
    public async IAsyncEnumerable<AgentStep> InvestigateEntityAsync(
        string entityType, string entityId, string timeRange,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var scratchpad = new StringBuilder();

        using var scope = _services.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<IGraphRepository>();
        var context = await BuildEntityContextAsync(repo, entityType, entityId, timeRange);

        scratchpad.AppendLine($"Task: Investigate this {entityType} thoroughly, analyzing all activity within the last {timeRange}.\n\n{context}");

        for (int i = 0; i < MaxIterations && !ct.IsCancellationRequested; i++)
        {
            _logger.LogDebug("Entity agent iteration {Iter} for {Type}/{Id}", i + 1, entityType, entityId);

            var systemPrompt = BuildSystemPrompt();
            var userPrompt = scratchpad + "\n\nNow think step-by-step about what to do next. " +
                "Either use a tool or provide your Final Answer as a comprehensive Markdown report.";

            var response = await _ollama.GenerateAsync(systemPrompt, userPrompt, ct);
            var parsed = ParseAgentResponse(response);

            if (parsed.Thought != null)
            {
                yield return new AgentStep("thought", parsed.Thought);
                scratchpad.AppendLine($"\nThought: {parsed.Thought}");
            }

            if (parsed.FinalAnswer != null)
            {
                yield return new AgentStep("answer", parsed.FinalAnswer);
                yield break;
            }

            if (parsed.Action != null && parsed.ActionInput != null)
            {
                yield return new AgentStep("action", $"🔧 {parsed.Action}: {parsed.ActionInput}");
                var observation = await ExecuteToolAsync(parsed.Action, parsed.ActionInput, ct);
                if (observation.Length > 3000)
                    observation = observation[..3000] + "\n... (truncated)";
                yield return new AgentStep("observation", observation);
                scratchpad.AppendLine($"\nAction: {parsed.Action}");
                scratchpad.AppendLine($"Action Input: {parsed.ActionInput}");
                scratchpad.AppendLine($"Observation: {observation}");
            }
            else if (parsed.FinalAnswer == null)
            {
                scratchpad.AppendLine($"\nThought: {response}");
                scratchpad.AppendLine("\nReminder: You MUST use a tool (Action/Action Input) or provide a Final Answer.");
            }
        }

        var finalPrompt = scratchpad +
            "\n\nYou have reached the maximum number of investigation steps. " +
            "Based on everything you've discovered, provide your Final Answer now as a detailed Markdown report.";
        var finalResponse = await _ollama.GenerateAsync(BuildSystemPrompt(), finalPrompt, ct);
        var finalParsed = ParseAgentResponse(finalResponse);
        yield return new AgentStep("answer", finalParsed.FinalAnswer ?? finalResponse);
    }

    private static async Task<string> BuildEntityContextAsync(
        IGraphRepository repo, string entityType, string entityId, string timeRange)
    {
        var sb = new StringBuilder();
        var fromDate = timeRange switch
        {
            "24h" => DateTime.UtcNow.AddHours(-24),
            "48h" => DateTime.UtcNow.AddHours(-48),
            "7d" => DateTime.UtcNow.AddDays(-7),
            "30d" => DateTime.UtcNow.AddDays(-30),
            _ => DateTime.UtcNow.AddHours(-24)
        };

        sb.AppendLine($"## Investigation Window: Last {timeRange} (from {fromDate:u} to {DateTime.UtcNow:u})");
        sb.AppendLine("Focus your analysis on events and activity within this time window.");
        sb.AppendLine();

        try
        {
            switch (entityType.ToLowerInvariant())
            {
                case "facility":
                    var fi = await repo.ExecuteCypherReadAsync(
                        "MATCH (f:Facility {facilityId: $id}) RETURN f.name AS name, f.type AS type, f.status AS status, f.criticality AS criticality LIMIT 1",
                        new Dictionary<string, object> { ["id"] = entityId });
                    if (fi.Count > 0)
                    {
                        var f = fi[0];
                        sb.AppendLine($"### Facility Under Investigation");
                        sb.AppendLine($"- Name: {f.GetValueOrDefault("name", entityId)}");
                        sb.AppendLine($"- Type: {f.GetValueOrDefault("type", "?")}");
                        sb.AppendLine($"- Status: {f.GetValueOrDefault("status", "?")}");
                        sb.AppendLine($"- Criticality: {f.GetValueOrDefault("criticality", "?")}");
                        sb.AppendLine($"- ID: {entityId}");
                    }
                    break;

                case "person":
                    var pi = await repo.ExecuteCypherReadAsync(
                        "MATCH (p:Person {personId: $id}) RETURN p.name AS name, p.role AS role, p.clearance AS clearance, p.personType AS type LIMIT 1",
                        new Dictionary<string, object> { ["id"] = entityId });
                    if (pi.Count > 0)
                    {
                        var p = pi[0];
                        sb.AppendLine($"### Person Under Investigation");
                        sb.AppendLine($"- Name: {p.GetValueOrDefault("name", entityId)}");
                        sb.AppendLine($"- Role: {p.GetValueOrDefault("role", "?")}");
                        sb.AppendLine($"- Clearance: {p.GetValueOrDefault("clearance", "?")}");
                        sb.AppendLine($"- Type: {p.GetValueOrDefault("type", "?")}");
                        sb.AppendLine($"- ID: {entityId}");
                    }
                    break;

                case "event":
                    var ei = await repo.ExecuteCypherReadAsync(
                        @"MATCH (e:Event {eventId: $id})
                          OPTIONAL MATCH (e)-[:OCCURRED_AT]->(f:Facility)
                          OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
                          RETURN e.eventType AS type, e.severity AS severity, e.description AS desc,
                                 e.timestamp AS ts, f.name AS facility, f.facilityId AS facId, p.name AS person LIMIT 1",
                        new Dictionary<string, object> { ["id"] = entityId });
                    if (ei.Count > 0)
                    {
                        var e = ei[0];
                        sb.AppendLine($"### Event Under Investigation");
                        sb.AppendLine($"- Type: {e.GetValueOrDefault("type", "?")}");
                        sb.AppendLine($"- Severity: {e.GetValueOrDefault("severity", "?")}");
                        sb.AppendLine($"- Description: {e.GetValueOrDefault("desc", "?")}");
                        sb.AppendLine($"- Timestamp: {e.GetValueOrDefault("ts", "?")}");
                        sb.AppendLine($"- Facility: {e.GetValueOrDefault("facility", "?")} ({e.GetValueOrDefault("facId", "?")})");
                        sb.AppendLine($"- Person: {e.GetValueOrDefault("person", "N/A")}");
                        sb.AppendLine($"- ID: {entityId}");
                    }
                    break;
            }
        }
        catch (Exception ex)
        {
            sb.AppendLine($"Error building context: {ex.Message}");
        }

        sb.AppendLine("\nUse your tools to investigate. Start with get_ontology, then use query_graph, search_events (with from/to for time filtering), and get_node_neighbors.");
        sb.AppendLine("Provide your Final Answer as a detailed Markdown report with ## sections, bullet points, **bold** highlights, and tables.");

        return sb.ToString();
    }

    // ═══════════════════════════════════════════════════════════════
    //  AGENTIC SEARCH
    // ═══════════════════════════════════════════════════════════════

    /// <inheritdoc />
    public async IAsyncEnumerable<AgentStep> AgenticSearchAsync(
        string userQuery, SearchResultDto searchResults,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"## User searched for: \"{userQuery}\"");
        sb.AppendLine($"\n### Elasticsearch returned {searchResults.TotalCount} results:\n");

        foreach (var hit in searchResults.Hits.Take(20))
        {
            sb.AppendLine($"- [{hit.Type}] (score: {hit.Score:F2}) {hit.Description}  [ID: {hit.Id}]");
        }

        sb.AppendLine("\nBased on these search results AND your knowledge of the water supply ontology, ");
        sb.AppendLine("provide a structured analysis with:");
        sb.AppendLine("1. **Key Findings**: What patterns or notable items appear in the results");
        sb.AppendLine("2. **Related Entities**: Facilities, persons, or events that might be connected");
        sb.AppendLine("3. **Investigation Recommendations**: What the analyst should investigate further");
        sb.AppendLine("4. **Risk Assessment**: Any potential threats or concerns identified");
        sb.AppendLine("\nYou can use your tools (query_graph, get_ontology, search_events, get_node_neighbors) to enrich your analysis.");
        sb.AppendLine("Provide your Final Answer as a structured Markdown report.");

        var scratchpad = new StringBuilder();
        scratchpad.AppendLine($"Task: Analyze search results and provide intelligent insights.\n\n{sb}");

        for (int i = 0; i < 5 && !ct.IsCancellationRequested; i++)
        {
            var response = await _ollama.GenerateAsync(BuildSystemPrompt(),
                scratchpad + "\n\nThink step-by-step. Use tools if needed, or provide your Final Answer.", ct);
            var parsed = ParseAgentResponse(response);

            if (parsed.Thought != null)
            {
                yield return new AgentStep("thought", parsed.Thought);
                scratchpad.AppendLine($"\nThought: {parsed.Thought}");
            }

            if (parsed.FinalAnswer != null)
            {
                yield return new AgentStep("answer", parsed.FinalAnswer);
                yield break;
            }

            if (parsed.Action != null && parsed.ActionInput != null)
            {
                yield return new AgentStep("action", $"🔧 {parsed.Action}: {parsed.ActionInput}");
                var observation = await ExecuteToolAsync(parsed.Action, parsed.ActionInput, ct);
                if (observation.Length > 2000) observation = observation[..2000] + "\n...";
                yield return new AgentStep("observation", observation);
                scratchpad.AppendLine($"\nAction: {parsed.Action}");
                scratchpad.AppendLine($"Action Input: {parsed.ActionInput}");
                scratchpad.AppendLine($"Observation: {observation}");
            }
            else
            {
                yield return new AgentStep("answer", response);
                yield break;
            }
        }

        yield return new AgentStep("answer", "Analysis complete based on available data.");
    }

    // ═══════════════════════════════════════════════════════════════
    //  PARSING
    // ═══════════════════════════════════════════════════════════════

    private string BuildSystemPrompt() =>
        $"""
        You are AEGIS AI Agent, an autonomous cybersecurity and critical-infrastructure
        analyst specializing in water supply systems.  You investigate risk cases by
        querying the Neo4j knowledge graph using Cypher and analyzing ontology relationships.

        You operate using the ReAct framework: Think → Act → Observe → Repeat.

        Always structure your response like this:
        Thought: <your reasoning about what to do next>
        Action: <tool_name>
        Action Input: <input for the tool>

        OR, when you have enough information:
        Final Answer: <your complete investigation report in Markdown>

        {ToolDescriptions}
        """;

    private static ParsedResponse ParseAgentResponse(string response)
    {
        var result = new ParsedResponse();

        var finalMatch = Regex.Match(response, @"Final Answer:\s*(.*)", RegexOptions.Singleline);
        if (finalMatch.Success)
        {
            result.FinalAnswer = finalMatch.Groups[1].Value.Trim();
            var beforeFinal = response[..finalMatch.Index];
            var thoughtMatch = Regex.Match(beforeFinal, @"Thought:\s*(.+?)(?=Action:|Final Answer:|$)", RegexOptions.Singleline);
            if (thoughtMatch.Success)
                result.Thought = thoughtMatch.Groups[1].Value.Trim();
            return result;
        }

        var thought = Regex.Match(response, @"Thought:\s*(.+?)(?=Action:|$)", RegexOptions.Singleline);
        if (thought.Success)
            result.Thought = thought.Groups[1].Value.Trim();

        var action = Regex.Match(response, @"Action:\s*(\S+)");
        var actionInput = Regex.Match(response, @"Action Input:\s*(.*?)(?=\nThought:|\nAction:|\nFinal Answer:|$)", RegexOptions.Singleline);
        if (action.Success)
            result.Action = action.Groups[1].Value.Trim();
        if (actionInput.Success)
            result.ActionInput = actionInput.Groups[1].Value.Trim();

        return result;
    }

    private static string FormatValue(object? val) => val switch
    {
        Dictionary<string, object> dict => "{" + string.Join(", ", dict.Take(6).Select(k => $"{k.Key}: {k.Value}")) + "}",
        List<object> list => "[" + string.Join(", ", list.Take(10)) + "]",
        _ => val?.ToString() ?? "null"
    };

    private class ParsedResponse
    {
        public string? Thought { get; set; }
        public string? Action { get; set; }
        public string? ActionInput { get; set; }
        public string? FinalAnswer { get; set; }
    }
}
