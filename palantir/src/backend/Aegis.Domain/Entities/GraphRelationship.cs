namespace Aegis.Domain.Entities;

/// <summary>
/// Represents a relationship/edge in the knowledge graph
/// </summary>
public class GraphRelationship
{
    public string Id { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string SourceLabel { get; set; } = string.Empty;
    public string TargetId { get; set; } = string.Empty;
    public string TargetLabel { get; set; } = string.Empty;
    public Dictionary<string, object> Properties { get; set; } = [];
}
