namespace Aegis.Domain.Entities;

/// <summary>
/// Base entity for all graph nodes in AEGIS
/// </summary>
public abstract class GraphEntity
{
    public string Id { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? UpdatedAt { get; set; }
    public Dictionary<string, object> Properties { get; set; } = [];
}
