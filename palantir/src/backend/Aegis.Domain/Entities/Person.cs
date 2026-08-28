namespace Aegis.Domain.Entities;

public class Person : GraphEntity
{
    public string PersonId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Role { get; set; } = string.Empty;
    public string Clearance { get; set; } = "L1";
    public string? OrganizationId { get; set; }
    public string? OrganizationName { get; set; }
    public string PersonType { get; set; } = "Employee"; // Employee, Contractor
}
