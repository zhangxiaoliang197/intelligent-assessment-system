namespace Aegis.Domain.Interfaces;

public interface ISearchService
{
    Task IndexEventAsync(string eventId, string description, string eventType, int severity, DateTime timestamp, string? facilityName);
    Task IndexDocumentAsync(string docId, string docType, string title, string content,
        string? sourceFile, string? facilityId, string? facilityName,
        string? personId, string? personName, DateTime timestamp, string? classification);
    Task<SearchResult> SearchAsync(string query, int page = 1, int pageSize = 20);
    Task EnsureIndexAsync();
}

public class SearchResult
{
    public int TotalCount { get; set; }
    public List<SearchHit> Hits { get; set; } = [];
}

public class SearchHit
{
    public string Id { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public double Score { get; set; }
    public string SourceType { get; set; } = "event";          // "event" | "document"
    public string? DocType { get; set; }                        // video_transcription, lab_analysis, etc.
    public string? FacilityName { get; set; }
    public string? PersonName { get; set; }
    public string? SourceFile { get; set; }
    public string? Classification { get; set; }
    public DateTime? Timestamp { get; set; }
    public Dictionary<string, object> Highlights { get; set; } = [];
}
