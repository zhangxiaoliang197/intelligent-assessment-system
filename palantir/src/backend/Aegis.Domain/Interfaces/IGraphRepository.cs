using Aegis.Domain.Entities;

namespace Aegis.Domain.Interfaces;

public interface IGraphRepository
{
    // Facilities
    Task<IEnumerable<Facility>> GetAllFacilitiesAsync();
    Task<Facility?> GetFacilityByIdAsync(string facilityId);

    // Events
    Task<IEnumerable<Event>> GetEventsAsync(EventFilter? filter = null);
    Task<IEnumerable<Event>> GetEventsByFacilityAsync(string facilityId);
    Task<Event?> GetEventByIdAsync(string eventId);

    // Persons
    Task<IEnumerable<Person>> GetAllPersonsAsync();
    Task<Person?> GetPersonByIdAsync(string personId);

    // Risk Cases
    Task<IEnumerable<RiskCase>> GetAllRiskCasesAsync();
    Task<RiskCase?> GetRiskCaseByIdAsync(string caseId);

    // Graph Exploration
    Task<GraphExplorationResult> ExploreNodeAsync(string nodeId, int depth = 2, List<string>? excludeLabels = null);
    Task<IEnumerable<GraphRelationship>> GetRelationshipsAsync(string nodeId);
    Task<GraphExplorationResult> GetCaseGraphAsync(string caseId);

    // Timeline
    Task<IEnumerable<Event>> GetTimelineAsync(DateTime from, DateTime to, string? facilityId = null);

    // Statistics
    Task<DashboardStats> GetDashboardStatsAsync();

    // Write operations
    Task<Event> CreateEventAsync(Event evt);
    Task CreateRiskCaseAsync(RiskCase riskCase);

    // Seed
    Task ClearAllDataAsync();
    Task SeedDataAsync(string cypherScript);

    // Link Analysis
    Task<LinkAnalysisResult> FindShortestPathsAsync(List<string> nodeIds, int maxDepth = 6);

    // Raw Cypher (read-only, for agent tools)
    Task<List<Dictionary<string, object>>> ExecuteCypherReadAsync(string cypher, Dictionary<string, object>? parameters = null);

    // Schema introspection
    Task<string> GetOntologySchemaAsync();
}

public class LinkAnalysisResult
{
    public List<DiscoveredPath> Paths { get; set; } = [];
    public GraphExplorationResult Graph { get; set; } = new();
}

public class DiscoveredPath
{
    public string FromId { get; set; } = string.Empty;
    public string FromLabel { get; set; } = string.Empty;
    public string ToId { get; set; } = string.Empty;
    public string ToLabel { get; set; } = string.Empty;
    public int Length { get; set; }
    public List<string> NodeSequence { get; set; } = [];
    public List<string> RelationshipSequence { get; set; } = [];
    public double Relevance { get; set; }
}

public class EventFilter
{
    public string? EventType { get; set; }
    public int? MinSeverity { get; set; }
    public int? Severity { get; set; }
    public string? FacilityId { get; set; }
    public DateTime? From { get; set; }
    public DateTime? To { get; set; }
}

public class GraphExplorationResult
{
    public List<GraphNode> Nodes { get; set; } = [];
    public List<GraphEdge> Edges { get; set; } = [];
}

public class GraphNode
{
    public string Id { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public Dictionary<string, object> Properties { get; set; } = [];
}

public class GraphEdge
{
    public string Id { get; set; } = string.Empty;
    public string Source { get; set; } = string.Empty;
    public string Target { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public Dictionary<string, object> Properties { get; set; } = [];
}

public class DashboardStats
{
    public int TotalFacilities { get; set; }
    public int TotalEvents { get; set; }
    public int OpenCases { get; set; }
    public int CriticalAlerts { get; set; }
    public int TotalPersons { get; set; }
    public List<EventTypeStat> EventsByType { get; set; } = [];
    public List<SeverityStat> EventsBySeverity { get; set; } = [];
}

public class EventTypeStat
{
    public string Type { get; set; } = string.Empty;
    public int Count { get; set; }
}

public class SeverityStat
{
    public int Severity { get; set; }
    public int Count { get; set; }
}
