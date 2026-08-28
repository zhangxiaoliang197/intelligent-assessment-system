using Aegis.Domain.Interfaces;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Aegis.API.Services;

/// <summary>
/// Background service that reindexes all Neo4j events and intel documents into OpenSearch periodically.
/// Ensures search stays in sync even if individual indexing failed during ingestion.
/// </summary>
public class SearchReindexService(
    IServiceProvider services,
    ILogger<SearchReindexService> logger) : BackgroundService
{
    private readonly TimeSpan _interval = TimeSpan.FromMinutes(2);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation("🔄 Search Reindex Service started – reindexing every {Interval} min", _interval.TotalMinutes);

        // Wait for initial startup and seed to complete
        await Task.Delay(TimeSpan.FromSeconds(15), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ReindexAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Search reindex failed");
            }

            await Task.Delay(_interval, stoppingToken);
        }
    }

    private async Task ReindexAsync(CancellationToken ct)
    {
        using var scope = services.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<IGraphRepository>();
        var search = scope.ServiceProvider.GetRequiredService<ISearchService>();

        // Reindex events
        var events = (await repo.GetEventsAsync(new EventFilter())).ToList();
        var eventsIndexed = 0;

        foreach (var evt in events)
        {
            if (ct.IsCancellationRequested) break;

            try
            {
                await search.IndexEventAsync(
                    evt.EventId, evt.Description, evt.EventType,
                    evt.Severity, evt.Timestamp, evt.FacilityName);
                eventsIndexed++;
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Failed to index event {EventId}", evt.EventId);
            }
        }

        // Reindex intel documents from file
        var docsIndexed = 0;
        var docsFile = "/app/seed-data/intel_documents.json";
        if (System.IO.File.Exists(docsFile))
        {
            try
            {
                var json = await System.IO.File.ReadAllTextAsync(docsFile, ct);
                var documents = System.Text.Json.JsonSerializer.Deserialize<List<IntelDocSeed>>(json,
                    new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true });

                if (documents is not null)
                {
                    foreach (var doc in documents)
                    {
                        if (ct.IsCancellationRequested) break;
                        try
                        {
                            var ts = DateTime.TryParse(doc.Timestamp, out var parsed) ? parsed : DateTime.UtcNow;
                            await search.IndexDocumentAsync(
                                doc.DocId, doc.DocType, doc.Title, doc.Content,
                                doc.SourceFile, doc.FacilityId, doc.FacilityName,
                                doc.PersonId, doc.PersonName, ts, doc.Classification);
                            docsIndexed++;
                        }
                        catch (Exception ex)
                        {
                            logger.LogWarning(ex, "Failed to index document {DocId}", doc.DocId);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Failed to load intel documents file for reindex");
            }
        }

        logger.LogInformation("🔄 Reindex complete – {Events}/{TotalEvents} events, {Docs} intel documents indexed",
            eventsIndexed, events.Count, docsIndexed);
    }

    private record IntelDocSeed(
        string DocId, string DocType, string Title, string Content,
        string? SourceFile, string? FacilityId, string? FacilityName,
        string? PersonId, string? PersonName, string? Timestamp, string? Classification);
}
