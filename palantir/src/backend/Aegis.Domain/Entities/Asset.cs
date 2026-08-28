namespace Aegis.Domain.Entities;

public class Asset : GraphEntity
{
    public string AssetId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty; // PLC, Valve, Pump, Camera
    public string? Model { get; set; }
    public string? Firmware { get; set; }
    public string? FacilityId { get; set; }
}
