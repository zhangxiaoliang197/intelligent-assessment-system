namespace Aegis.Application.DTOs;

public record DashboardStatsDto(
    int TotalFacilities,
    int TotalEvents,
    int OpenCases,
    int CriticalAlerts,
    int TotalPersons,
    List<TypeCountDto> EventsByType,
    List<SeverityCountDto> EventsBySeverity
);

public record TypeCountDto(string Type, int Count);

public record SeverityCountDto(int Severity, int Count);
