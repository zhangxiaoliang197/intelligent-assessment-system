namespace Aegis.Application.DTOs;

public record EventDto(
    string EventId,
    string EventType,
    string Description,
    int Severity,
    DateTime Timestamp,
    string? FacilityId,
    string? FacilityName,
    string? PersonId,
    string? PersonName,
    Dictionary<string, object> Metadata
);
