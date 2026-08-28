namespace Aegis.API.Contracts;

/// <summary>Request body for event ingestion.</summary>
public record IngestEventRequest(
    string EventType,
    string Description,
    int Severity,
    string? FacilityId,
    string? PersonId,
    Dictionary<string, object>? Metadata
);
