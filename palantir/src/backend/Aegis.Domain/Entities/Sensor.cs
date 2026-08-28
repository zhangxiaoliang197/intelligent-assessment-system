namespace Aegis.Domain.Entities;

public class Sensor : GraphEntity
{
    public string SensorId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Metric { get; set; } = string.Empty;
    public string Unit { get; set; } = string.Empty;
    public double NormalMin { get; set; }
    public double NormalMax { get; set; }
    public string FacilityId { get; set; } = string.Empty;
}
