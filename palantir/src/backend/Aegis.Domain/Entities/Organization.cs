namespace Aegis.Domain.Entities;

public class Organization : GraphEntity
{
    public string OrgId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty; // WaterUtility, Contractor, SecurityProvider
}
