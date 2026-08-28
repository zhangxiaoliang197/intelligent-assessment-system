using Aegis.API.Hubs;
using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Aegis.API.Services;

/// <summary>
/// Background inference engine that analyzes incoming events and auto-creates risk cases
/// when suspicious patterns are detected.
/// 
/// Patterns detected:
/// 1. Severity cluster: ≥2 high-severity events (≥4) at the same facility within a time window
/// 2. Multi-type correlation: ≥3 different high-severity event types at same facility (attack chain)
/// 3. Off-hours anomaly: unauthorized access or cyber alerts outside business hours (22:00–06:00)
/// 4. Repeated actor: same person involved in ≥2 high-severity events
/// 5. Sensor anomaly spike: ≥3 anomalous SensorReading events at the same facility (water quality degradation)
/// 6. Geographic spread: same event type at ≥3 different facilities within window (cross-site threat)
/// 7. Escalation cascade: events escalating in severity (3→4→5) at same facility
/// 8. Cyber-Physical convergence: CyberAlert + PhysicalAnomaly at same facility (hybrid attack)
/// </summary>
public class InferenceEngine(
    IServiceProvider services,
    ILogger<InferenceEngine> logger) : BackgroundService
{
    private readonly TimeSpan _interval = TimeSpan.FromSeconds(30);
    private DateTime _lastAnalysis = DateTime.UnixEpoch;

    public void RequestFullScan() => _lastAnalysis = DateTime.UnixEpoch;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation("🧠 Inference Engine started – analyzing events every {Interval}s", _interval.TotalSeconds);

        // Wait for services to initialize
        await Task.Delay(5000, stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await AnalyzeEventsAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Inference engine error");
            }

            await Task.Delay(_interval, stoppingToken);
        }
    }

    private async Task AnalyzeEventsAsync(CancellationToken ct)
    {
        using var scope = services.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<IGraphRepository>();
        var notifier = scope.ServiceProvider.GetRequiredService<AlertNotificationService>();

        // Get events since last analysis
        var filter = new EventFilter { From = _lastAnalysis };
        var recentEvents = (await repo.GetEventsAsync(filter)).ToList();
        _lastAnalysis = DateTime.UtcNow;

        if (recentEvents.Count == 0) return;

        logger.LogDebug("Inference engine analyzing {Count} recent events", recentEvents.Count);

        var newCases = new List<RiskCase>();

        // Pattern 1: Severity cluster at same facility
        var facilityGroups = recentEvents
            .Where(e => e.Severity >= 4 && e.FacilityId != null)
            .GroupBy(e => e.FacilityId);

        foreach (var group in facilityGroups)
        {
            var events = group.ToList();
            if (events.Count >= 2)
            {
                var riskCase = CreateRiskCase(
                    $"High-Severity Cluster at {events.First().FacilityName ?? group.Key}",
                    $"Detected {events.Count} high-severity events at facility {events.First().FacilityName ?? group.Key}: " +
                    string.Join("; ", events.Select(e => $"{e.EventType} (SEV-{e.Severity})")),
                    events,
                    group.Key!,
                    confidence: Math.Min(0.95, 0.5 + events.Count * 0.15),
                    riskScore: Math.Min(10.0, events.Average(e => e.Severity) * 1.5 + events.Count * 0.5)
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 2: Multi-type correlation (attack chain) - different event types at same facility
        foreach (var group in facilityGroups)
        {
            var events = group.ToList();
            var distinctTypes = events.Select(e => e.EventType).Distinct().ToList();
            if (distinctTypes.Count >= 3)
            {
                var riskCase = CreateRiskCase(
                    $"Multi-Vector Attack Pattern at {events.First().FacilityName ?? group.Key}",
                    $"Correlated {distinctTypes.Count} different event types at {events.First().FacilityName ?? group.Key}: " +
                    string.Join(", ", distinctTypes) + ". This pattern suggests a coordinated attack.",
                    events,
                    group.Key!,
                    confidence: Math.Min(0.98, 0.6 + distinctTypes.Count * 0.12),
                    riskScore: Math.Min(10.0, 7.0 + distinctTypes.Count * 0.5)
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 3: Off-hours anomaly (includes Access events – off-hours badge swipes are suspicious)
        var offHoursEvents = recentEvents
            .Where(e => e.Severity >= 3 &&
                        (e.EventType == "UnauthorizedAccess" || e.EventType == "CyberAlert" || e.EventType == "Access") &&
                        (e.Timestamp.Hour >= 22 || e.Timestamp.Hour < 6))
            .ToList();

        if (offHoursEvents.Count >= 1)
        {
            var byFacility = offHoursEvents.GroupBy(e => e.FacilityId ?? "unknown");
            foreach (var group in byFacility)
            {
                var events = group.ToList();
                var riskCase = CreateRiskCase(
                    $"Off-Hours Security Alert at {events.First().FacilityName ?? group.Key}",
                    $"Detected {events.Count} security event(s) outside business hours (22:00-06:00): " +
                    string.Join("; ", events.Select(e => $"{e.EventType} at {e.Timestamp:HH:mm}")),
                    events,
                    group.Key!,
                    confidence: 0.7 + events.Count * 0.1,
                    riskScore: Math.Min(10.0, 5.0 + events.Count * 1.5)
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 4: Repeated actor
        var personEvents = recentEvents
            .Where(e => e.PersonId != null && e.Severity >= 3)
            .GroupBy(e => e.PersonId);

        foreach (var group in personEvents)
        {
            var events = group.ToList();
            if (events.Count >= 2)
            {
                var riskCase = CreateRiskCase(
                    $"Suspicious Repeated Activity by {events.First().PersonName ?? group.Key}",
                    $"Person {events.First().PersonName ?? group.Key} involved in {events.Count} security events: " +
                    string.Join("; ", events.Select(e => $"{e.EventType} at {e.FacilityName ?? e.FacilityId}")),
                    events,
                    events.First().FacilityId,
                    confidence: 0.6 + events.Count * 0.12,
                    riskScore: Math.Min(10.0, 4.0 + events.Count * 2.0),
                    personIds: events.Select(e => e.PersonId!).Distinct().ToList()
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 5: Sensor anomaly spike – many abnormal SensorReading events at a facility
        var sensorAnomalies = recentEvents
            .Where(e => e.EventType == "SensorReading" && e.Severity >= 2 && e.FacilityId != null)
            .GroupBy(e => e.FacilityId);

        foreach (var group in sensorAnomalies)
        {
            var events = group.ToList();
            if (events.Count >= 3)
            {
                var riskCase = CreateRiskCase(
                    $"Water Quality Degradation at {events.First().FacilityName ?? group.Key}",
                    $"Detected {events.Count} anomalous sensor readings at {events.First().FacilityName ?? group.Key}. " +
                    $"Multiple sensors reporting out-of-range values simultaneously suggests contamination or equipment failure. " +
                    $"Events: {string.Join("; ", events.Take(5).Select(e => e.Description))}",
                    events,
                    group.Key!,
                    confidence: Math.Min(0.95, 0.55 + events.Count * 0.12),
                    riskScore: Math.Min(10.0, 5.0 + events.Count * 1.0)
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 6: Geographic spread – same event type hitting ≥3 different facilities
        var eventsByType = recentEvents
            .Where(e => e.Severity >= 3 && e.FacilityId != null)
            .GroupBy(e => e.EventType);

        foreach (var typeGroup in eventsByType)
        {
            var distinctFacilities = typeGroup.Select(e => e.FacilityId).Distinct().ToList();
            if (distinctFacilities.Count >= 3)
            {
                var events = typeGroup.ToList();
                var facilityNames = events
                    .GroupBy(e => e.FacilityId)
                    .Select(g => g.First().FacilityName ?? g.Key!)
                    .Distinct().ToList();

                var riskCase = CreateRiskCase(
                    $"Cross-Site {typeGroup.Key} Pattern Detected",
                    $"Same event type '{typeGroup.Key}' detected across {distinctFacilities.Count} different facilities: " +
                    $"{string.Join(", ", facilityNames)}. " +
                    "This geographic spread pattern may indicate a coordinated attack or widespread environmental incident.",
                    events,
                    events.First().FacilityId,
                    confidence: Math.Min(0.97, 0.65 + distinctFacilities.Count * 0.1),
                    riskScore: Math.Min(10.0, 6.5 + distinctFacilities.Count * 1.0)
                );
                newCases.Add(riskCase);
            }
        }

        // Pattern 7: Escalation cascade – severity increasing over time at same facility
        var cascadeCandidates = recentEvents
            .Where(e => e.Severity >= 2 && e.FacilityId != null)
            .GroupBy(e => e.FacilityId);

        foreach (var group in cascadeCandidates)
        {
            var ordered = group.OrderBy(e => e.Timestamp).ToList();
            if (ordered.Count >= 3)
            {
                // Check for monotonically increasing severity
                bool escalating = true;
                for (int i = 1; i < ordered.Count; i++)
                {
                    if (ordered[i].Severity < ordered[i - 1].Severity)
                    {
                        escalating = false;
                        break;
                    }
                }

                if (escalating && ordered.Last().Severity > ordered.First().Severity)
                {
                    var riskCase = CreateRiskCase(
                        $"Severity Escalation Cascade at {ordered.First().FacilityName ?? group.Key}",
                        $"Detected escalating severity pattern at {ordered.First().FacilityName ?? group.Key}: " +
                        $"SEV-{ordered.First().Severity} → SEV-{ordered.Last().Severity} across {ordered.Count} events. " +
                        "This progressive escalation may indicate a developing crisis requiring immediate attention.",
                        ordered,
                        group.Key!,
                        confidence: Math.Min(0.92, 0.6 + (ordered.Last().Severity - ordered.First().Severity) * 0.15),
                        riskScore: Math.Min(10.0, ordered.Last().Severity * 1.8 + 1.0)
                    );
                    newCases.Add(riskCase);
                }
            }
        }

        // Pattern 8: Cyber-Physical convergence – CyberAlert + PhysicalAnomaly at same facility
        var cyberPhysicalFacilities = recentEvents
            .Where(e => (e.EventType == "CyberAlert" || e.EventType == "PhysicalAnomaly") && e.FacilityId != null)
            .GroupBy(e => e.FacilityId);

        foreach (var group in cyberPhysicalFacilities)
        {
            var events = group.ToList();
            var types = events.Select(e => e.EventType).Distinct().ToList();
            if (types.Contains("CyberAlert") && types.Contains("PhysicalAnomaly"))
            {
                var riskCase = CreateRiskCase(
                    $"Cyber-Physical Hybrid Attack at {events.First().FacilityName ?? group.Key}",
                    $"Simultaneous CyberAlert and PhysicalAnomaly events detected at {events.First().FacilityName ?? group.Key}. " +
                    $"Cyber events: {events.Count(e => e.EventType == "CyberAlert")}, " +
                    $"Physical events: {events.Count(e => e.EventType == "PhysicalAnomaly")}. " +
                    "Converging cyber and physical threats strongly suggest a coordinated hybrid attack on infrastructure.",
                    events,
                    group.Key!,
                    confidence: 0.9,
                    riskScore: Math.Min(10.0, 8.0 + events.Count * 0.3)
                );
                newCases.Add(riskCase);
            }
        }

        // Persist and notify
        foreach (var riskCase in newCases)
        {
            try
            {
                // Check for duplicate cases (same facility, similar title within 5 minutes)
                var existing = await repo.GetAllRiskCasesAsync();
                var isDuplicate = existing.Any(c =>
                    c.LinkedFacilityId == riskCase.LinkedFacilityId &&
                    c.Title == riskCase.Title &&
                    c.CreatedAt > DateTime.UtcNow.AddMinutes(-5));

                if (isDuplicate)
                {
                    logger.LogDebug("Skipping duplicate case: {Title}", riskCase.Title);
                    continue;
                }

                await repo.CreateRiskCaseAsync(riskCase);

                await notifier.NotifyNewRiskCaseAsync(
                    riskCase.CaseId, riskCase.Title, riskCase.RiskScore);

                logger.LogInformation(
                    "🔍 Inference engine created case {CaseId}: {Title} (risk={Score:F1}, confidence={Conf:F2})",
                    riskCase.CaseId, riskCase.Title, riskCase.RiskScore, riskCase.Confidence);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Failed to create risk case {CaseId}", riskCase.CaseId);
            }
        }
    }

    private RiskCase CreateRiskCase(
        string title, string description, List<Event> events,
        string? facilityId, double confidence, double riskScore,
        List<string>? personIds = null)
    {
        return new RiskCase
        {
            CaseId = $"CASE-INF-{DateTime.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid().ToString("N")[..6].ToUpper()}",
            Title = title,
            Description = description,
            Status = riskScore >= 8.0 ? "Escalated" : "Open",
            Confidence = Math.Min(confidence, 1.0),
            RiskScore = Math.Min(riskScore, 10.0),
            LinkedEventIds = events.Select(e => e.EventId).ToList(),
            LinkedFacilityId = facilityId,
            LinkedPersonIds = personIds ?? events
                .Where(e => e.PersonId != null)
                .Select(e => e.PersonId!)
                .Distinct()
                .ToList(),
            CreatedAt = DateTime.UtcNow
        };
    }
}
