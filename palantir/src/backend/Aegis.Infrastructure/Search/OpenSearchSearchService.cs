using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using OpenSearch.Client;

namespace Aegis.Infrastructure.Search;

public class OpenSearchSearchService : ISearchService
{
    private readonly OpenSearchClient _client;
    private readonly ILogger<OpenSearchSearchService> _logger;
    private const string EventsIndex = "aegis-events";
    private const string IntelIndex = "aegis-intel";

    public OpenSearchSearchService(IConfiguration configuration, ILogger<OpenSearchSearchService> logger)
    {
        _logger = logger;
        var url = configuration["ConnectionStrings:OpenSearch"] ?? "http://localhost:9200";
        var settings = new ConnectionSettings(new Uri(url))
            .DefaultIndex(EventsIndex)
            .ServerCertificateValidationCallback((_, _, _, _) => true);
        _client = new OpenSearchClient(settings);
    }

    public async Task EnsureIndexAsync()
    {
        // Events index
        var exists = await _client.Indices.ExistsAsync(EventsIndex);
        if (!exists.Exists)
        {
            var response = await _client.Indices.CreateAsync(EventsIndex, c => c
                .Map<EventDocument>(m => m
                    .Properties(p => p
                        .Keyword(k => k.Name(n => n.EventId))
                        .Keyword(k => k.Name(n => n.EventType))
                        .Text(t => t.Name(n => n.Description))
                        .Number(n => n.Name(nm => nm.Severity).Type(NumberType.Integer))
                        .Date(d => d.Name(n => n.Timestamp))
                        .Text(t => t.Name(n => n.FacilityName))
                    )
                )
            );
            _logger.LogInformation("Created OpenSearch index: {Index} (acknowledged={Ack})", EventsIndex, response.Acknowledged);
        }

        // Intel documents index
        var existsIntel = await _client.Indices.ExistsAsync(IntelIndex);
        if (!existsIntel.Exists)
        {
            var response = await _client.Indices.CreateAsync(IntelIndex, c => c
                .Map<IntelDocument>(m => m
                    .Properties(p => p
                        .Keyword(k => k.Name(n => n.DocId))
                        .Keyword(k => k.Name(n => n.DocType))
                        .Text(t => t.Name(n => n.Title).Boost(2))
                        .Text(t => t.Name(n => n.Content))
                        .Keyword(k => k.Name(n => n.SourceFile))
                        .Keyword(k => k.Name(n => n.FacilityId))
                        .Text(t => t.Name(n => n.FacilityName))
                        .Keyword(k => k.Name(n => n.PersonId))
                        .Text(t => t.Name(n => n.PersonName))
                        .Date(d => d.Name(n => n.Timestamp))
                        .Keyword(k => k.Name(n => n.Classification))
                    )
                )
            );
            _logger.LogInformation("Created OpenSearch index: {Index} (acknowledged={Ack})", IntelIndex, response.Acknowledged);
        }
    }

    public async Task IndexEventAsync(string eventId, string description, string eventType, int severity,
        DateTime timestamp, string? facilityName)
    {
        var doc = new EventDocument
        {
            EventId = eventId,
            Description = description,
            EventType = eventType,
            Severity = severity,
            Timestamp = timestamp,
            FacilityName = facilityName ?? ""
        };

        await _client.IndexAsync(doc, idx => idx.Index(EventsIndex).Id(eventId));
    }

    public async Task IndexDocumentAsync(string docId, string docType, string title, string content,
        string? sourceFile, string? facilityId, string? facilityName,
        string? personId, string? personName, DateTime timestamp, string? classification)
    {
        var doc = new IntelDocument
        {
            DocId = docId,
            DocType = docType,
            Title = title,
            Content = content,
            SourceFile = sourceFile ?? "",
            FacilityId = facilityId ?? "",
            FacilityName = facilityName ?? "",
            PersonId = personId ?? "",
            PersonName = personName ?? "",
            Timestamp = timestamp,
            Classification = classification ?? "INTERNAL"
        };

        await _client.IndexAsync(doc, idx => idx.Index(IntelIndex).Id(docId));
    }

    public async Task<SearchResult> SearchAsync(string query, int page = 1, int pageSize = 20)
    {
        var from = (page - 1) * pageSize;
        var hits = new List<SearchHit>();
        long totalCount = 0;

        // Search events index
        var evtResponse = await _client.SearchAsync<EventDocument>(s => s
            .Index(EventsIndex)
            .From(0)
            .Size(pageSize)
            .Query(q => q
                .MultiMatch(mm => mm
                    .Query(query)
                    .Fields(f => f
                        .Field(p => p.Description, boost: 3)
                        .Field(p => p.EventType, boost: 2)
                        .Field(p => p.FacilityName)
                    )
                    .Fuzziness(Fuzziness.Auto)
                )
            )
        );

        foreach (var h in evtResponse.Hits)
        {
            hits.Add(new SearchHit
            {
                Id = h.Source?.EventId ?? "",
                Type = h.Source?.EventType ?? "",
                Description = h.Source?.Description ?? "",
                Score = h.Score ?? 0,
                SourceType = "event",
                FacilityName = h.Source?.FacilityName,
                Timestamp = h.Source?.Timestamp
            });
        }
        totalCount += evtResponse.Total;

        // Search intel documents index
        var intelResponse = await _client.SearchAsync<IntelDocument>(s => s
            .Index(IntelIndex)
            .From(0)
            .Size(pageSize)
            .Query(q => q
                .MultiMatch(mm => mm
                    .Query(query)
                    .Fields(f => f
                        .Field(p => p.Title, boost: 3)
                        .Field(p => p.Content, boost: 2)
                        .Field(p => p.DocType)
                        .Field(p => p.FacilityName)
                        .Field(p => p.PersonName)
                    )
                    .Fuzziness(Fuzziness.Auto)
                )
            )
        );

        foreach (var h in intelResponse.Hits)
        {
            hits.Add(new SearchHit
            {
                Id = h.Source?.DocId ?? "",
                Type = h.Source?.DocType ?? "",
                Description = h.Source?.Title ?? "",
                Score = h.Score ?? 0,
                SourceType = "document",
                DocType = h.Source?.DocType,
                FacilityName = h.Source?.FacilityName,
                PersonName = h.Source?.PersonName,
                SourceFile = h.Source?.SourceFile,
                Classification = h.Source?.Classification,
                Timestamp = h.Source?.Timestamp
            });
        }
        totalCount += intelResponse.Total;

        // Sort all results by score descending, then paginate
        var sorted = hits.OrderByDescending(h => h.Score).ToList();

        return new SearchResult
        {
            TotalCount = (int)totalCount,
            Hits = sorted.Skip(from).Take(pageSize).ToList()
        };
    }

    // ── Internal document models ──

    private class EventDocument
    {
        public string EventId { get; set; } = "";
        public string Description { get; set; } = "";
        public string EventType { get; set; } = "";
        public int Severity { get; set; }
        public DateTime Timestamp { get; set; }
        public string FacilityName { get; set; } = "";
    }

    private class IntelDocument
    {
        public string DocId { get; set; } = "";
        public string DocType { get; set; } = "";
        public string Title { get; set; } = "";
        public string Content { get; set; } = "";
        public string SourceFile { get; set; } = "";
        public string FacilityId { get; set; } = "";
        public string FacilityName { get; set; } = "";
        public string PersonId { get; set; } = "";
        public string PersonName { get; set; } = "";
        public DateTime Timestamp { get; set; }
        public string Classification { get; set; } = "";
    }
}
