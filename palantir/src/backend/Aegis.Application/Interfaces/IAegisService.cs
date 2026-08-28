using Aegis.Application.DTOs;

namespace Aegis.Application.Interfaces;

/// <summary>
/// Core application service — all read and write operations for AEGIS entities.
/// Replaces the MediatR query/command handler pattern with a simple direct service.
/// </summary>
public interface IAegisService
{
    // ── Dashboard ──
    Task<DashboardStatsDto> GetDashboardStatsAsync(CancellationToken ct = default);

    // ── Facilities ──
    Task<IEnumerable<FacilityDto>> GetFacilitiesAsync(CancellationToken ct = default);

    // ── Events ──
    Task<IEnumerable<EventDto>> GetEventsAsync(
        string? eventType = null, int? minSeverity = null, int? severity = null,
        string? facilityId = null, DateTime? from = null, DateTime? to = null,
        CancellationToken ct = default);

    Task<EventDto> IngestEventAsync(
        string eventType, string description, int severity,
        string? facilityId, string? personId,
        Dictionary<string, object>? metadata,
        CancellationToken ct = default);

    // ── Persons ──
    Task<IEnumerable<PersonDto>> GetPersonsAsync(CancellationToken ct = default);

    // ── Risk Cases ──
    Task<IEnumerable<RiskCaseDto>> GetRiskCasesAsync(CancellationToken ct = default);
    Task<GraphDto> GetCaseGraphAsync(string caseId, CancellationToken ct = default);

    // ── Graph ──
    Task<GraphDto> ExploreGraphAsync(string nodeId, int depth = 2, List<string>? excludeLabels = null, CancellationToken ct = default);
    Task<LinkAnalysisDto> FindHiddenLinksAsync(List<string> nodeIds, int maxDepth = 6, CancellationToken ct = default);

    // ── Timeline ──
    Task<IEnumerable<TimelineEventDto>> GetTimelineAsync(
        DateTime from, DateTime to, string? facilityId = null, CancellationToken ct = default);

    // ── Search ──
    Task<SearchResultDto> SearchAsync(string query, int page = 1, int pageSize = 20, CancellationToken ct = default);
}
