using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Logging;

namespace Aegis.Application.Services;

/// <summary>
/// Implements all AEGIS read/write operations with straightforward domain→DTO mapping.
/// No mediator, no handlers — just a service that calls repositories and returns DTOs.
/// </summary>
public sealed class AegisService(
    IGraphRepository repo,
    ISearchService search,
    ILogger<AegisService> logger) : IAegisService
{
    // ── Dashboard ──

    public async Task<DashboardStatsDto> GetDashboardStatsAsync(CancellationToken ct)
    {
        var stats = await repo.GetDashboardStatsAsync();
        return new DashboardStatsDto(
            stats.TotalFacilities, stats.TotalEvents, stats.OpenCases,
            stats.CriticalAlerts, stats.TotalPersons,
            stats.EventsByType.Select(e => new TypeCountDto(e.Type, e.Count)).ToList(),
            stats.EventsBySeverity.Select(e => new SeverityCountDto(e.Severity, e.Count)).ToList());
    }

    // ── Facilities ──

    public async Task<IEnumerable<FacilityDto>> GetFacilitiesAsync(CancellationToken ct)
    {
        var facilities = await repo.GetAllFacilitiesAsync();
        return facilities.Select(f => new FacilityDto(
            f.FacilityId, f.Name, f.Type, f.Status, f.Criticality,
            f.Latitude, f.Longitude, f.Sensors.Count, f.Assets.Count));
    }

    // ── Events ──

    public async Task<IEnumerable<EventDto>> GetEventsAsync(
        string? eventType, int? minSeverity, int? severity,
        string? facilityId, DateTime? from, DateTime? to, CancellationToken ct)
    {
        var filter = new EventFilter
        {
            EventType = eventType,
            MinSeverity = minSeverity,
            Severity = severity,
            FacilityId = facilityId,
            From = from,
            To = to
        };

        var events = await repo.GetEventsAsync(filter);
        return events.Select(MapEvent);
    }

    public async Task<EventDto> IngestEventAsync(
        string eventType, string description, int severity,
        string? facilityId, string? personId,
        Dictionary<string, object>? metadata, CancellationToken ct)
    {
        var eventId = $"EVT-{DateTime.UtcNow:yyyyMMddHHmmss}-{Random.Shared.Next(1000, 9999)}";

        var evt = new Event
        {
            EventId = eventId,
            EventType = eventType,
            Description = description,
            Severity = severity,
            Timestamp = DateTime.UtcNow,
            FacilityId = facilityId,
            PersonId = personId,
            Metadata = metadata ?? []
        };

        var created = await repo.CreateEventAsync(evt);

        try
        {
            await search.IndexEventAsync(
                created.EventId, created.Description, created.EventType,
                created.Severity, created.Timestamp, created.FacilityName);
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Failed to index event {EventId} in Elasticsearch", eventId);
        }

        logger.LogInformation("Ingested event {EventId} type={Type} severity={Severity} facility={Facility}",
            eventId, eventType, severity, facilityId);

        return MapEvent(created);
    }

    // ── Persons ──

    public async Task<IEnumerable<PersonDto>> GetPersonsAsync(CancellationToken ct)
    {
        var persons = await repo.GetAllPersonsAsync();
        return persons.Select(p => new PersonDto(
            p.PersonId, p.Name, p.Role, p.Clearance, p.PersonType,
            p.OrganizationId, p.OrganizationName));
    }

    // ── Risk Cases ──

    public async Task<IEnumerable<RiskCaseDto>> GetRiskCasesAsync(CancellationToken ct)
    {
        var cases = await repo.GetAllRiskCasesAsync();
        return cases.Select(c => new RiskCaseDto(
            c.CaseId, c.Title, c.Status, c.Confidence, c.RiskScore,
            c.Description, c.CreatedAt, c.LinkedFacilityId,
            c.LinkedEventIds.Count, c.LinkedPersonIds));
    }

    public async Task<GraphDto> GetCaseGraphAsync(string caseId, CancellationToken ct)
    {
        var result = await repo.GetCaseGraphAsync(caseId);
        return MapGraph(result);
    }

    // ── Graph ──

    public async Task<GraphDto> ExploreGraphAsync(string nodeId, int depth, List<string>? excludeLabels, CancellationToken ct)
    {
        var result = await repo.ExploreNodeAsync(nodeId, depth, excludeLabels);
        return MapGraph(result);
    }

    public async Task<LinkAnalysisDto> FindHiddenLinksAsync(List<string> nodeIds, int maxDepth, CancellationToken ct)
    {
        var result = await repo.FindShortestPathsAsync(nodeIds, maxDepth);
        var graph = MapGraph(result.Graph);
        var paths = result.Paths.Select(p => new DiscoveredPathDto(
            p.FromId, p.FromLabel, p.ToId, p.ToLabel, p.Length,
            p.NodeSequence, p.RelationshipSequence, p.Relevance)).ToList();

        var directCount = paths.Count(p => p.Length == 1);
        var indirectCount = paths.Count(p => p.Length > 1);
        var summary = $"Analyzed {nodeIds.Count} entities. Found {paths.Count} paths: {directCount} direct, {indirectCount} hidden links via intermediate entities.";

        return new LinkAnalysisDto(paths, graph, paths.Count, summary);
    }

    // ── Timeline ──

    public async Task<IEnumerable<TimelineEventDto>> GetTimelineAsync(
        DateTime from, DateTime to, string? facilityId, CancellationToken ct)
    {
        var events = await repo.GetTimelineAsync(from, to, facilityId);
        return events.Select(e => new TimelineEventDto(
            e.EventId, e.EventType, e.Description, e.Severity,
            e.Timestamp, e.FacilityName, e.PersonName));
    }

    // ── Search ──

    public async Task<SearchResultDto> SearchAsync(string query, int page, int pageSize, CancellationToken ct)
    {
        var result = await search.SearchAsync(query, page, pageSize);
        return new SearchResultDto(
            result.TotalCount,
            result.Hits.Select(h => new SearchHitDto(
                h.Id, h.Type, h.Description, h.Score,
                h.SourceType, h.DocType, h.FacilityName, h.PersonName,
                h.SourceFile, h.Classification, h.Timestamp)).ToList());
    }

    // ── Private Mappers ──

    private static EventDto MapEvent(Event e) => new(
        e.EventId, e.EventType, e.Description, e.Severity, e.Timestamp,
        e.FacilityId, e.FacilityName, e.PersonId, e.PersonName, e.Metadata);

    private static GraphDto MapGraph(GraphExplorationResult r) => new(
        r.Nodes.Select(n => new GraphNodeDto(n.Id, n.Label, n.Type, n.Properties)).ToList(),
        r.Edges.Select(e => new GraphEdgeDto(e.Id, e.Source, e.Target, e.Type, e.Properties)).ToList());
}
