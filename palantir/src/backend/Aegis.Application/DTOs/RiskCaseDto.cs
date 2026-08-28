namespace Aegis.Application.DTOs;

public record RiskCaseDto(
    string CaseId,
    string Title,
    string Status,
    double Confidence,
    double RiskScore,
    string Description,
    DateTime CreatedAt,
    string? FacilityName,
    int LinkedEventsCount,
    List<string> LinkedPersonNames
);
