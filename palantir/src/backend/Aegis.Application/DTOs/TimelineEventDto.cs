namespace Aegis.Application.DTOs;

public record TimelineEventDto(
    string EventId,
    string EventType,
    string Description,
    int Severity,
    DateTime Timestamp,
    string? FacilityName,
    string? PersonName
);
