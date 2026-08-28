namespace Aegis.Domain.Entities;

public class Facility : GraphEntity
{
    public string FacilityId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty; // WaterTreatmentPlant, PumpStation, Reservoir, DistributionNode
    public string Status { get; set; } = "Operational";
    public string Criticality { get; set; } = "MEDIUM"; // LOW, MEDIUM, HIGH, CRITICAL
    public double Latitude { get; set; }
    public double Longitude { get; set; }
    public List<Sensor> Sensors { get; set; } = [];
    public List<Asset> Assets { get; set; } = [];
}
