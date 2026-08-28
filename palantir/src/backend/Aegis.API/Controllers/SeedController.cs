using Aegis.Domain.Interfaces;
using Aegis.API.Services;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class SeedController(
    IGraphRepository repo,
    ISearchService search,
    ILogger<SeedController> logger,
    InferenceEngine inferenceEngine) : ControllerBase
{
    [HttpPost]
    public async Task<IActionResult> Seed()
    {
        var seedFile = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "seed.cypher");
        if (!System.IO.File.Exists(seedFile))
            seedFile = "/app/seed-data/seed.cypher";
        if (!System.IO.File.Exists(seedFile))
            seedFile = "/var/lib/neo4j/import/seed.cypher";
        if (!System.IO.File.Exists(seedFile))
            return NotFound("Seed file not found");

        await repo.ClearAllDataAsync();

        var script = await System.IO.File.ReadAllTextAsync(seedFile);
        await repo.SeedDataAsync(script);
        logger.LogInformation("Database seeded to Neo4j successfully");

        var eventsIndexed = await IndexEventsAsync();
        var docsIndexed = await IndexIntelDocumentsAsync();
        inferenceEngine.RequestFullScan();
        return Ok(new { message = "Database seeded successfully", eventsIndexed, documentsIndexed = docsIndexed });
    }

    [HttpPost("reindex")]
    public async Task<IActionResult> Reindex()
    {
        var eventsIndexed = await IndexEventsAsync();
        var docsIndexed = await IndexIntelDocumentsAsync();
        return Ok(new { message = "Search reindex complete", eventsIndexed, documentsIndexed = docsIndexed });
    }

    private async Task<int> IndexEventsAsync()
    {
        var events = await repo.GetEventsAsync(new EventFilter());
        var indexed = 0;
        foreach (var evt in events)
        {
            await search.IndexEventAsync(
                evt.EventId, evt.Description, evt.EventType,
                evt.Severity, evt.Timestamp, evt.FacilityName);
            indexed++;
        }
        logger.LogInformation("Indexed {Count} events into OpenSearch", indexed);
        return indexed;
    }

    private async Task<int> IndexIntelDocumentsAsync()
    {
        // Load intel_documents.json from seed data directory
        var docsFile = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "intel_documents.json");
        if (!System.IO.File.Exists(docsFile))
            docsFile = "/app/seed-data/intel_documents.json";
        if (!System.IO.File.Exists(docsFile))
        {
            logger.LogWarning("Intel documents file not found – skipping document indexing");
            return 0;
        }

        var json = await System.IO.File.ReadAllTextAsync(docsFile);
        var documents = System.Text.Json.JsonSerializer.Deserialize<List<IntelDocumentSeed>>(json,
            new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        if (documents is null) return 0;

        var indexed = 0;
        foreach (var doc in documents)
        {
            try
            {
                var ts = DateTime.TryParse(doc.Timestamp, out var parsed) ? parsed : DateTime.UtcNow;
                await search.IndexDocumentAsync(
                    doc.DocId, doc.DocType, doc.Title, doc.Content,
                    doc.SourceFile, doc.FacilityId, doc.FacilityName,
                    doc.PersonId, doc.PersonName, ts, doc.Classification);
                indexed++;
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Failed to index document {DocId}", doc.DocId);
            }
        }
        logger.LogInformation("Indexed {Count} intel documents into OpenSearch", indexed);
        return indexed;
    }

    private record IntelDocumentSeed(
        string DocId, string DocType, string Title, string Content,
        string? SourceFile, string? FacilityId, string? FacilityName,
        string? PersonId, string? PersonName, string? Timestamp, string? Classification);
}
