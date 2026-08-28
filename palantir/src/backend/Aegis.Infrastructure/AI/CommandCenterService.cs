using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Aegis.Infrastructure.AI;

/// <summary>
/// Multi-agent Command Center: specialized AI agents with different profiles
/// that translate natural language → Cypher → intelligence analysis.
///
/// Agents:
///   🎖️ CENTCOM   — Military/defense analyst: threat assessment, attack vectors, force protection
///   🏛️ CIVILCOM  — Civil infrastructure analyst: public safety, service continuity, regulatory
///   ⚙️ OPSCOM    — Operations analyst: SCADA, maintenance, sensor data, asset health
///   🚨 SENTINEL  — Automated alert agent: generates alerts, escalations, notifications
/// </summary>
public sealed class CommandCenterService : ICommandCenterService
{
    private readonly IOllamaService _ollama;
    private readonly IServiceProvider _services;
    private readonly ILogger<CommandCenterService> _logger;

    private static readonly List<AgentProfile> Profiles =
    [
        new("centcom", "CENTCOM", "Military Intelligence Analyst",
            "Threat assessment, attack vector analysis, adversary profiling, force protection recommendations. Thinks like a military intelligence officer.",
            "🎖️", "red"),
        new("civilcom", "CIVILCOM", "Civil Infrastructure Analyst",
            "Public safety assessment, service continuity, regulatory compliance, citizen impact analysis. Thinks like a civil protection officer.",
            "🏛️", "blue"),
        new("opscom", "OPSCOM", "Operations Analyst",
            "SCADA systems, sensor data analysis, maintenance scheduling, asset health monitoring. Thinks like a plant operations engineer.",
            "⚙️", "amber"),
        new("sentinel", "SENTINEL", "Automated Alert Agent",
            "Threat detection, automated alerting, escalation protocols, notification dispatch. Acts as an autonomous watchdog that can trigger alerts to persons and facilities.",
            "🚨", "rose"),
    ];

    private static readonly Dictionary<string, string> AgentPersonas = new()
    {
        ["centcom"] = """
            You are CENTCOM, a military intelligence analyst embedded in the AEGIS water supply
            intelligence platform. You think like a defense/intelligence professional:

            YOUR MINDSET:
            - Classify threats by type: state-sponsored, insider, opportunistic, terrorist
            - Use military intelligence frameworks: indicators & warnings, pattern of life, attack kill chain
            - Assess ADVERSARY CAPABILITY + INTENT + OPPORTUNITY
            - Recommend force protection measures and countermeasures
            - Use military terminology: OPSEC, HUMINT, SIGINT, TTPs, IOCs, THREATCON levels
            - Assign THREATCON levels: NORMAL, ALPHA, BRAVO, CHARLIE, DELTA
            - Think about attribution: who benefits? what nation-state or group?

            RESPONSE STYLE:
            - Structured like a military intelligence brief
            - Use ## SITUATION, ## THREAT ASSESSMENT, ## INDICATORS & WARNINGS, ## RECOMMENDATIONS
            - Be decisive and direct — commanders need clear recommendations
            - Rate confidence levels: LOW / MODERATE / HIGH / CONFIRMED
            """,

        ["civilcom"] = """
            You are CIVILCOM, a civil infrastructure protection analyst in the AEGIS platform.
            You think like a civil protection / emergency management professional:

            YOUR MINDSET:
            - Focus on PUBLIC SAFETY: how many citizens are affected?
            - Assess service continuity: which areas lose water supply?
            - Regulatory compliance: EU Drinking Water Directive, national CNPIC regulations
            - Coordinate with emergency services: fire, police, health authorities
            - Think about vulnerable populations: hospitals, schools, elderly care
            - Communication strategy: what do we tell the public?
            - Recovery timeline: how long to restore normal service?

            RESPONSE STYLE:
            - Structured like a civil protection report
            - Use ## PUBLIC IMPACT, ## SERVICE DISRUPTION, ## REGULATORY IMPLICATIONS, ## COMMUNICATION PLAN
            - Empathetic but factual — focus on protecting citizens
            - Include population estimates and affected zones
            """,

        ["opscom"] = """
            You are OPSCOM, a water utility operations analyst in the AEGIS platform.
            You think like a senior plant operations engineer:

            YOUR MINDSET:
            - Focus on SCADA/ICS systems: PLC configurations, HMI alarms, network segments
            - Sensor data interpretation: what do the readings actually mean?
            - Maintenance analysis: was there scheduled work? who was the contractor?
            - Asset health: valve positions, pump status, chemical dosing rates
            - Process chemistry: chlorine residual, pH, turbidity, flow rates
            - Root cause analysis: mechanical failure vs deliberate tampering
            - Standard operating procedures: what should have happened vs what did

            RESPONSE STYLE:
            - Technical and precise — use engineering units (mg/L, bar, m³/h)
            - Use ## SYSTEM STATUS, ## SENSOR ANALYSIS, ## ROOT CAUSE, ## CORRECTIVE ACTIONS
            - Include specific readings, thresholds, and tolerances
            - Reference SCADA tags and equipment IDs
            """,

        ["sentinel"] = """
            You are SENTINEL, an automated alert and notification agent in the AEGIS platform.
            You are a WATCHDOG — your job is to detect threats and generate actionable alerts.

            YOUR MINDSET:
            - Analyze the query to identify potential threats
            - Determine WHO needs to be notified (specific persons, facilities, organizations)
            - Assess SEVERITY: info, warning, critical
            - Generate concrete alert actions with specific targets
            - Think about escalation chains: operator → supervisor → director → emergency services
            - Consider time sensitivity: how urgent is this?

            SPECIAL CAPABILITY — ALERT GENERATION:
            When you identify a threat, you MUST generate alert actions using this exact format
            inside your Final Answer (you can generate multiple):

            :::ALERT:::
            type: notify_person | alert_facility | escalate_case | broadcast
            target: <person ID, facility ID, or "all">
            message: <the alert message>
            severity: info | warning | critical
            :::END_ALERT:::

            RESPONSE STYLE:
            - Start with ## THREAT DETECTED or ## SITUATION NORMAL
            - Use ## ALERT ACTIONS, ## ESCALATION PROTOCOL, ## NOTIFICATION CHAIN
            - Be urgent and action-oriented
            - Always end with specific alert actions
            """
    };

    public CommandCenterService(
        IOllamaService ollama,
        IServiceProvider services,
        ILogger<CommandCenterService> logger)
    {
        _ollama = ollama;
        _services = services;
        _logger = logger;
    }

    public List<AgentProfile> GetAgentProfiles() => Profiles;

    public async IAsyncEnumerable<AgentStep> QueryAsync(
        string agentId,
        string naturalLanguageQuery,
        string? conversationHistory,
        [EnumeratorCancellation] CancellationToken ct)
    {
        if (!AgentPersonas.TryGetValue(agentId.ToLowerInvariant(), out var persona))
        {
            yield return new AgentStep("answer", $"[ERROR] Unknown agent: {agentId}");
            yield break;
        }

        var profile = Profiles.First(p => p.Id == agentId.ToLowerInvariant());
        yield return new AgentStep("agent", JsonSerializer.Serialize(new { profile.Id, profile.Name, profile.Role, profile.Icon }));

        // Collect all steps in a list to avoid yield-in-try-catch limitation
        var steps = await ExecuteQueryPipelineAsync(agentId, profile, persona, naturalLanguageQuery, conversationHistory, ct);

        foreach (var step in steps)
            yield return step;
    }

    private async Task<List<AgentStep>> ExecuteQueryPipelineAsync(
        string agentId, AgentProfile profile, string persona,
        string query, string? history, CancellationToken ct)
    {
        var steps = new List<AgentStep>();

        try
        {
            using var scope = _services.CreateScope();
            var repo = scope.ServiceProvider.GetRequiredService<IGraphRepository>();

            // Step 1: Get ontology for NL→Cypher translation
            var ontologySchema = await repo.GetOntologySchemaAsync();

            // Step 2: Generate Cypher from natural language
            steps.Add(new AgentStep("thought", $"Analyzing query as {profile.Name}: \"{query}\""));

            var cypherPrompt = BuildCypherGenerationPrompt(ontologySchema, query, history);
            var cypherResponse = await _ollama.GenerateAsync(cypherPrompt, query, ct);
            var (cypher, explanation) = ParseCypherResponse(cypherResponse);

            if (cypher != null)
            {
                steps.Add(new AgentStep("cypher", JsonSerializer.Serialize(new { query = cypher, explanation })));

                // Step 3: Execute Cypher (with one retry on failure)
                string resultText;
                try
                {
                    var normalized = cypher.Trim().ToUpperInvariant();
                    if (normalized.Contains("DELETE") || normalized.Contains("DETACH") ||
                        normalized.Contains("CREATE") || normalized.Contains("MERGE") ||
                        normalized.Contains("SET ") || normalized.Contains("REMOVE"))
                    {
                        steps.Add(new AgentStep("observation", "ERROR: Only read-only queries allowed."));
                        return steps;
                    }

                    if (!normalized.Contains("LIMIT"))
                        cypher += " LIMIT 25";

                    var rows = await repo.ExecuteCypherReadAsync(cypher);
                    resultText = FormatQueryResults(rows);
                    steps.Add(new AgentStep("observation", resultText));
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Cypher execution failed, retrying: {Cypher}", cypher);
                    steps.Add(new AgentStep("thought", $"Query failed: {ex.Message}. Generating corrected query..."));

                    // Retry: ask LLM to fix the query with the error message
                    var retryPrompt = cypherPrompt + $"\n\nPREVIOUS ATTEMPT FAILED:\nQuery: {cypher}\nError: {ex.Message}\n\nGenerate a CORRECTED Cypher query. Follow the schema directions EXACTLY.";
                    var retryResponse = await _ollama.GenerateAsync(retryPrompt, query, ct);
                    var (retryCypher, retryExplanation) = ParseCypherResponse(retryResponse);

                    if (retryCypher != null)
                    {
                        cypher = retryCypher;
                        steps.Add(new AgentStep("cypher", JsonSerializer.Serialize(new { query = cypher, explanation = retryExplanation })));

                        try
                        {
                            var normalizedRetry = cypher.Trim().ToUpperInvariant();
                            if (!normalizedRetry.Contains("LIMIT"))
                                cypher += " LIMIT 25";

                            var rows = await repo.ExecuteCypherReadAsync(cypher);
                            resultText = FormatQueryResults(rows);
                            steps.Add(new AgentStep("observation", resultText));
                        }
                        catch (Exception retryEx)
                        {
                            _logger.LogWarning(retryEx, "Retry also failed: {Cypher}", cypher);
                            resultText = $"Query failed after retry: {retryEx.Message}";
                            steps.Add(new AgentStep("observation", resultText));
                        }
                    }
                    else
                    {
                        resultText = $"Query failed: {ex.Message}";
                        steps.Add(new AgentStep("observation", resultText));
                    }
                }

                // Step 4: Agent analysis with persona
                steps.Add(new AgentStep("thought", $"Analyzing results through {profile.Role} lens..."));

                var analysisPrompt = BuildAnalysisPrompt(persona, query, cypher, resultText, history);
                var analysis = await _ollama.GenerateAsync(analysisPrompt, "Provide your analysis now.", ct);

                // Parse alerts from SENTINEL
                if (agentId.Equals("sentinel", StringComparison.OrdinalIgnoreCase))
                {
                    var alerts = ParseAlerts(analysis);
                    foreach (var alert in alerts)
                        steps.Add(new AgentStep("alert", JsonSerializer.Serialize(alert)));
                }

                steps.Add(new AgentStep("answer", analysis));
            }
            else
            {
                // No Cypher generated — direct analysis
                steps.Add(new AgentStep("thought", "Processing as analytical question (no graph query needed)..."));

                var directPrompt = BuildAnalysisPrompt(persona, query, null, null, history);
                var directAnalysis = await _ollama.GenerateAsync(directPrompt,
                    "Provide your analysis based on your expertise.", ct);

                if (agentId.Equals("sentinel", StringComparison.OrdinalIgnoreCase))
                {
                    var alerts = ParseAlerts(directAnalysis);
                    foreach (var alert in alerts)
                        steps.Add(new AgentStep("alert", JsonSerializer.Serialize(alert)));
                }

                steps.Add(new AgentStep("answer", directAnalysis));
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Command center pipeline failed");
            steps.Add(new AgentStep("answer", $"[ERROR] {ex.Message}"));
        }

        return steps;
    }

    // ═══════════════════════════════════════════════════════════════
    //  PROMPT BUILDERS
    // ═══════════════════════════════════════════════════════════════

    private static string BuildCypherGenerationPrompt(string ontology, string query, string? history)
    {
        var sb = new StringBuilder();
        sb.AppendLine("""
            You are a Cypher query generator for a Neo4j 5 knowledge graph about water supply infrastructure.
            Your ONLY job is to translate the user's natural language question into a valid Cypher MATCH/RETURN query.

            ═══════════════════════════════════════════════
            CRITICAL RULES — FOLLOW EXACTLY:
            ═══════════════════════════════════════════════
            - Generate ONLY read-only Cypher (MATCH, OPTIONAL MATCH, WITH, WHERE, RETURN, ORDER BY, LIMIT)
            - NEVER use CREATE, MERGE, DELETE, SET, REMOVE
            - Always include LIMIT (max 30)
            - Use ONLY the exact node labels, property names, and relationship types listed below
            - The user may write in Spanish, English, or any language — always generate valid Cypher
            - Neo4j 5 SYNTAX: NEVER use size() on patterns. Use COUNT { pattern } instead.
              WRONG:  size((p)-[:REL]->())
              CORRECT: COUNT { (p)-[:REL]->() }
            - Neo4j DATE FUNCTIONS: NEVER use DATEADD, CURRENT_DATE(), GETDATE(), NOW() — these are SQL, not Cypher!
              Timestamps in this database are ISO-8601 STRINGS (e.g., "2026-01-15T08:30:00Z").
              DO NOT use datetime() for filtering — just ORDER BY timestamp DESC to get the most recent.
              For "recent" queries: ORDER BY e.timestamp DESC LIMIT 30
              NEVER use: DATEADD(), CURRENT_DATE(), datetime() - duration(), GETDATE()

            ═══════════════════════════════════════════════
            EXACT GRAPH SCHEMA — USE ONLY THESE:
            ═══════════════════════════════════════════════

            ## NODE LABELS AND PROPERTIES:

            :Person (also labeled :Employee or :Contractor)
              Properties: personId (string), name (string), role (string), personType ("employee"|"contractor"), clearance (string)

            :Facility (also labeled :WaterTreatmentPlant, :PumpStation, :Reservoir, or :DistributionNode)
              Properties: facilityId (string), name (string), type (string), status (string), latitude (float), longitude (float)

            :Event (also labeled :PhysicalAnomalyEvent, :AccessEvent, :CyberAlertEvent, :CitizenReportEvent, or :MaintenanceEvent)
              Properties: eventId (string), eventType (string), severity (INTEGER 0-5, where 5=most severe), description (string), timestamp (string), windowId (string)
              AccessEvent extra: authorized (boolean), accessPoint (string)
              CyberAlertEvent extra: alertType (string), targetSystem (string)
              PhysicalAnomalyEvent extra: metric (string), value (float)
              CitizenReportEvent extra: area (string), reportCount (integer)

            :Asset (also labeled :RTU, :PLC, :Pump, :Valve, :Camera, or :FlowMeter)
              Properties: assetId (string), name (string), type (string), model (string), firmware (string)

            :Sensor
              Properties: sensorId (string), type (string), unit (string)

            :Organization
              Properties: orgId (string), name (string), type (string)

            :Location
              Properties: locationId (string), name (string), latitude (float), longitude (float)

            :RiskCase (also labeled :SuspectedSabotage)
              Properties: caseId (string), title (string), status (string), riskScore (float)

            :Document (also labeled :MaintenanceReport, :LabAnalysis, :ScadaLog, :EmailCommunication, :WorkerProfile, :VideoTranscription, :RegulatoryInspection, :IncidentPhoto, :AccessBadgeRecord, :DatabaseExtract)
              Properties: docId (string), title (string), type (string), classification (string)

            ## RELATIONSHIPS (source)-[:TYPE]->(target) — DIRECTION MATTERS!

            (Person)-[:BELONGS_TO]->(Organization)        Person works for an organization
            (Person)-[:CONNECTED_TO]->(Person)            Two persons are socially/professionally connected
            (Facility)-[:HAS_ASSET]->(Asset)              Facility owns an asset
            (Facility)-[:HAS_SENSOR]->(Sensor)            Facility has a sensor
            (Facility)-[:LOCATED_AT]->(Location)          Facility is at a location
            (Organization)-[:OPERATES_IN]->(Location)     Organization operates in a location
            (Event)-[:OCCURS_AT]->(Facility)              Event happened at a facility  ← NOTE DIRECTION
            (Event)-[:INVOLVES_PERSON]->(Person)          Event involves a person       ← NOTE DIRECTION
            (Event)-[:INVOLVES_ASSET]->(Asset)            Event involves an asset       ← NOTE DIRECTION
            (RiskCase)-[:LINKED_EVENT]->(Event)           Risk case is linked to an event
            (RiskCase)-[:LINKED_FACILITY]->(Facility)     Risk case is linked to a facility
            (RiskCase)-[:LINKED_PERSON]->(Person)         Risk case is linked to a person
            (Document)-[:REFERENCES_FACILITY]->(Facility) Document references a facility
            (Document)-[:REFERENCES_PERSON]->(Person)     Document references a person

            ═══════════════════════════════════════════════
            ABSOLUTELY CRITICAL — READ CAREFULLY:
            ═══════════════════════════════════════════════

            ## ANTI-HALLUCINATION RULES:
            1. ONLY use relationships listed above. If a relationship is NOT in the list, it DOES NOT EXIST.
            2. NEVER invent relationships. The following DO NOT EXIST:
               - INVOLVES_EVENT ← DOES NOT EXIST
               - HAS_EVENT ← DOES NOT EXIST
               - REPORTED_BY ← DOES NOT EXIST
               - DETECTED_BY ← DOES NOT EXIST
               - MONITORED_BY ← DOES NOT EXIST
            3. :Sensor and :Asset are TERMINAL nodes — they connect ONLY to Facility, not to Event.
               To find sensors/assets related to events, go through Facility:
               (Event)-[:OCCURS_AT]->(Facility)-[:HAS_SENSOR]->(Sensor) ← CORRECT multi-hop path
               (Event)-[:OCCURS_AT]->(Facility)-[:HAS_ASSET]->(Asset) ← CORRECT multi-hop path for non-cyber events
               (Event)-[:INVOLVES_ASSET]->(Asset) ← CORRECT only for CyberAlertEvent
            4. severity is an INTEGER (0=none, 1=low, 2=medium, 3=high, 4=critical, 5=extreme)
               To filter "high severity" use: WHERE e.severity >= 3
            5. Events point TO facilities: (Event)-[:OCCURS_AT]->(Facility), NOT the reverse
            6. Events point TO persons: (Event)-[:INVOLVES_PERSON]->(Person), NOT the reverse
            7. To find persons involved in events, ALWAYS match FROM the Event side:
               MATCH (e:Event)-[:INVOLVES_PERSON]->(p:Person) ← CORRECT
               MATCH (p:Person)-[:INVOLVES_EVENT]->(e:Event) ← WRONG! INVOLVES_EVENT does not exist!
            8. When filtering by event sub-type, use multi-label: (e:Event:PhysicalAnomalyEvent) or WHERE e.eventType = "physical_anomaly"
            9. NEVER reverse the arrow direction of any relationship listed above.

            ═══════════════════════════════════════════════
            EXAMPLE QUERIES (study these carefully):
            ═══════════════════════════════════════════════

            Q: Show all facilities
            CYPHER: MATCH (f:Facility) RETURN f.facilityId AS id, f.name AS name, f.type AS type, f.status AS status LIMIT 30
            EXPLANATION: Lists all facilities with their basic info.

            Q: Events at pump stations with high severity
            CYPHER: MATCH (e:Event)-[:OCCURS_AT]->(f:Facility:PumpStation) WHERE e.severity >= 3 RETURN e.eventId AS id, e.eventType AS type, e.severity AS severity, e.description AS description, f.name AS facility LIMIT 30
            EXPLANATION: High-severity events occurring at pump station facilities.

            Q: Persons connected to more than one high-severity event
            CYPHER: MATCH (e:Event)-[:INVOLVES_PERSON]->(p:Person) WHERE e.severity >= 3 WITH p, COUNT(e) AS eventCount WHERE eventCount > 1 RETURN p.name AS person, p.role AS role, eventCount ORDER BY eventCount DESC LIMIT 30
            EXPLANATION: Persons involved in multiple high-severity events, sorted by count.

            Q: Show risk cases and their linked events
            CYPHER: MATCH (rc:RiskCase)-[:LINKED_EVENT]->(e:Event) RETURN rc.caseId AS caseId, rc.title AS title, rc.riskScore AS risk, e.eventType AS eventType, e.severity AS severity LIMIT 30
            EXPLANATION: Risk cases with their associated events.

            Q: Contractors who accessed critical facilities
            CYPHER: MATCH (e:Event:AccessEvent)-[:INVOLVES_PERSON]->(p:Person:Contractor), (e)-[:OCCURS_AT]->(f:Facility) RETURN p.name AS contractor, f.name AS facility, e.authorized AS authorized, e.timestamp AS time LIMIT 30
            EXPLANATION: Access events involving contractors at facilities.

            Q: Assets affected by cyber alerts
            CYPHER: MATCH (e:Event:CyberAlertEvent)-[:INVOLVES_ASSET]->(a:Asset) RETURN e.alertType AS alert, a.name AS asset, a.type AS assetType, e.severity AS severity, e.description AS description LIMIT 30
            EXPLANATION: Assets involved in cyber alert events.

            Q: Sensors with anomalous readings (MULTI-HOP — sensors connect through facilities)
            CYPHER: MATCH (e:Event:PhysicalAnomalyEvent)-[:OCCURS_AT]->(f:Facility)-[:HAS_SENSOR]->(s:Sensor) RETURN s.type AS sensorType, s.unit AS unit, e.metric AS metric, e.value AS reading, e.severity AS severity, f.name AS facility, e.timestamp AS time ORDER BY e.timestamp DESC LIMIT 30
            EXPLANATION: Sensors at facilities where physical anomaly events occurred, most recent first.

            Q: Assets at facilities that had cyber attacks
            CYPHER: MATCH (e:Event:CyberAlertEvent)-[:OCCURS_AT]->(f:Facility)-[:HAS_ASSET]->(a:Asset) RETURN a.name AS asset, a.type AS assetType, f.name AS facility, e.alertType AS alert, e.severity AS severity LIMIT 30
            EXPLANATION: Assets at facilities where cyber alert events occurred.

            Q: Persons and the organizations they belong to
            CYPHER: MATCH (p:Person)-[:BELONGS_TO]->(o:Organization) RETURN p.name AS person, p.role AS role, o.name AS organization LIMIT 30
            EXPLANATION: Lists persons with their organization affiliations.

            Q: Documents referencing a specific facility
            CYPHER: MATCH (d:Document)-[:REFERENCES_FACILITY]->(f:Facility) RETURN d.title AS document, d.type AS docType, f.name AS facility LIMIT 30
            EXPLANATION: Intel documents that reference facilities.

            Q: Full chain: risk case → events → persons → organizations
            CYPHER: MATCH (rc:RiskCase)-[:LINKED_EVENT]->(e:Event)-[:INVOLVES_PERSON]->(p:Person)-[:BELONGS_TO]->(o:Organization) RETURN rc.title AS riskCase, e.eventType AS eventType, p.name AS person, o.name AS organization LIMIT 30
            EXPLANATION: Traces from risk cases through events to involved persons and their organizations.

            Q: Facilities with the most events
            CYPHER: MATCH (e:Event)-[:OCCURS_AT]->(f:Facility) WITH f, COUNT(e) AS eventCount RETURN f.name AS facility, f.type AS type, eventCount ORDER BY eventCount DESC LIMIT 30
            EXPLANATION: Facilities ranked by total number of events.

            """);

        if (!string.IsNullOrEmpty(history))
        {
            sb.AppendLine("PREVIOUS CONVERSATION:");
            sb.AppendLine(history);
        }

        sb.AppendLine("""

            ═══════════════════════════════════════════════
            RESPONSE FORMAT — respond EXACTLY like this:
            ═══════════════════════════════════════════════
            CYPHER: <your cypher query here>
            EXPLANATION: <one-line explanation of what the query does>

            If the question doesn't need a graph query (e.g., "what is AEGIS?"), respond:
            CYPHER: NONE
            EXPLANATION: <answer the question directly>
            """);

        return sb.ToString();
    }

    private static string BuildAnalysisPrompt(
        string persona, string query, string? cypher, string? results, string? history)
    {
        var sb = new StringBuilder();
        sb.AppendLine(persona);
        sb.AppendLine();
        sb.AppendLine($"USER QUERY: {query}");

        if (cypher != null)
            sb.AppendLine($"\nCYPHER EXECUTED: {cypher}");
        if (results != null)
            sb.AppendLine($"\nQUERY RESULTS:\n{results}");
        if (!string.IsNullOrEmpty(history))
            sb.AppendLine($"\nPREVIOUS CONVERSATION:\n{history}");

        sb.AppendLine("""

            INSTRUCTIONS:
            - Analyze the data from YOUR professional perspective
            - Be specific: reference actual entity names, IDs, and values from the results
            - If results are empty, explain what that means in your domain
            - Provide actionable recommendations
            - Use Markdown formatting with ## headers, **bold**, bullet points, and tables
            - Respond in the same language the user wrote the query in
            """);

        return sb.ToString();
    }

    // ═══════════════════════════════════════════════════════════════
    //  PARSING
    // ═══════════════════════════════════════════════════════════════

    private static (string? Cypher, string? Explanation) ParseCypherResponse(string response)
    {
        var cypherMatch = Regex.Match(response, @"CYPHER:\s*(.+?)(?=EXPLANATION:|$)", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        var explMatch = Regex.Match(response, @"EXPLANATION:\s*(.+?)$", RegexOptions.Singleline | RegexOptions.IgnoreCase);

        var cypher = cypherMatch.Success ? cypherMatch.Groups[1].Value.Trim() : null;
        var explanation = explMatch.Success ? explMatch.Groups[1].Value.Trim() : null;

        if (cypher != null && (cypher.Equals("NONE", StringComparison.OrdinalIgnoreCase) || cypher.Length < 5))
            cypher = null;

        // Clean markdown code fences if present
        if (cypher != null)
        {
            cypher = Regex.Replace(cypher, @"```(?:cypher)?\s*", "").Trim();
            cypher = cypher.TrimEnd('`').Trim();
        }

        return (cypher, explanation);
    }

    private static List<AlertAction> ParseAlerts(string analysis)
    {
        var alerts = new List<AlertAction>();
        var pattern = @":::ALERT:::\s*type:\s*(.+?)\s*target:\s*(.+?)\s*message:\s*(.+?)\s*severity:\s*(.+?)\s*:::END_ALERT:::";
        var matches = Regex.Matches(analysis, pattern, RegexOptions.Singleline | RegexOptions.IgnoreCase);

        foreach (Match match in matches)
        {
            alerts.Add(new AlertAction(
                Type: match.Groups[1].Value.Trim(),
                Target: match.Groups[2].Value.Trim(),
                Message: match.Groups[3].Value.Trim(),
                Severity: match.Groups[4].Value.Trim(),
                Timestamp: DateTime.UtcNow.ToString("o")
            ));
        }

        // If SENTINEL didn't use the format, generate a default alert
        if (alerts.Count == 0 && analysis.Contains("THREAT DETECTED", StringComparison.OrdinalIgnoreCase))
        {
            alerts.Add(new AlertAction(
                Type: "broadcast",
                Target: "all",
                Message: "SENTINEL has detected a potential threat. Review the analysis for details.",
                Severity: "warning",
                Timestamp: DateTime.UtcNow.ToString("o")
            ));
        }

        return alerts;
    }

    private static string FormatQueryResults(List<Dictionary<string, object>> rows)
    {
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

    private static string FormatValue(object? val) => val switch
    {
        Dictionary<string, object> dict => "{" + string.Join(", ", dict.Take(6).Select(k => $"{k.Key}: {k.Value}")) + "}",
        List<object> list => "[" + string.Join(", ", list.Take(10)) + "]",
        _ => val?.ToString() ?? "null"
    };
}
