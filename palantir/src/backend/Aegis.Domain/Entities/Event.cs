namespace Aegis.Domain.Entities;

public class Event : GraphEntity
{
    public string EventId { get; set; } = string.Empty;
    public string EventType { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public int Severity { get; set; }
    public DateTime Timestamp { get; set; }
    public string? WindowId { get; set; }
    public string? FacilityId { get; set; }
    public string? FacilityName { get; set; }
    public string? PersonId { get; set; }
    public string? PersonName { get; set; }
    public string? AssetId { get; set; }
    public Dictionary<string, object> Metadata { get; set; } = [];
}

public class PhysicalAnomalyEvent : Event
{
    public string Metric { get; set; } = string.Empty;
    public double Value { get; set; }
}

public class AccessEvent : Event
{
    public string AccessPoint { get; set; } = string.Empty;
    public bool Authorized { get; set; }
}

public class CyberAlertEvent : Event
{
    public string? SourceIP { get; set; }
    public string TargetSystem { get; set; } = string.Empty;
    public string AlertType { get; set; } = string.Empty;
}

public class CitizenReportEvent : Event
{
    public int ReportCount { get; set; }
    public string Area { get; set; } = string.Empty;
}

public class MaintenanceEvent : Event
{
    public string? WorkOrderId { get; set; }
}
