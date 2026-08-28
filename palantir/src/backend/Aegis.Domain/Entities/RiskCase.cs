namespace Aegis.Domain.Entities;

public class RiskCase : GraphEntity
{
    public string CaseId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Status { get; set; } = "Open"; // Open, Investigating, Closed, Escalated
    public double Confidence { get; set; }
    public double RiskScore { get; set; }
    public string Description { get; set; } = string.Empty;
    public List<string> LinkedEventIds { get; set; } = [];
    public string? LinkedFacilityId { get; set; }
    public List<string> LinkedPersonIds { get; set; } = [];
}
