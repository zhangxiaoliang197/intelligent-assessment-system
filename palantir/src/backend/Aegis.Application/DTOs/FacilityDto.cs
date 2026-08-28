namespace Aegis.Application.DTOs;

public record FacilityDto(
    string FacilityId,
    string Name,
    string Type,
    string Status,
    string Criticality,
    double Latitude,
    double Longitude,
    int SensorCount,
    int AssetCount
);
