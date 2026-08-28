namespace Aegis.Application.DTOs;

public record PersonDto(
    string PersonId,
    string Name,
    string Role,
    string Clearance,
    string PersonType,
    string? OrganizationId,
    string? OrganizationName
);
