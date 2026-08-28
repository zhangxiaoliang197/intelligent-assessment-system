namespace Aegis.Application.DTOs;

public record SearchResultDto(
    int TotalCount,
    List<SearchHitDto> Hits
);

public record SearchHitDto(
    string Id,
    string Type,
    string Description,
    double Score,
    string SourceType = "event",
    string? DocType = null,
    string? FacilityName = null,
    string? PersonName = null,
    string? SourceFile = null,
    string? Classification = null,
    DateTime? Timestamp = null
);
