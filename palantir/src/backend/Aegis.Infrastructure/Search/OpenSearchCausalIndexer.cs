using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using OpenSearch.Client;

namespace Aegis.Infrastructure.Search;

public sealed class OpenSearchCausalIndexer : ICausalSearchIndexer
{
    private const string IndexName = "aegis-causal-v5";
    private readonly IOpenSearchClient _client;
    private readonly ILogger<OpenSearchCausalIndexer> _logger;

    public OpenSearchCausalIndexer(IConfiguration configuration, ILogger<OpenSearchCausalIndexer> logger)
    {
        _logger = logger;
        var url = configuration["ConnectionStrings:OpenSearch"] ?? "http://localhost:9200";
        var settings = new ConnectionSettings(new Uri(url))
            .DefaultIndex(IndexName)
            .ServerCertificateValidationCallback((_, _, _, _) => true);

        var username = configuration["OpenSearch:Username"];
        var password = configuration["OpenSearch:Password"];
        if (!string.IsNullOrWhiteSpace(username)) settings = settings.BasicAuthentication(username, password);

        _client = new OpenSearchClient(settings);
    }

    public async Task EnsureIndexAsync(CancellationToken cancellationToken = default)
    {
        var exists = await _client.Indices.ExistsAsync(IndexName);
        if (exists.Exists) return;

        var response = await _client.Indices.CreateAsync(IndexName, c => c
            .Map<CausalSearchDocument>(m => m
                .Properties(p => p
                    .Keyword(k => k.Name(x => x.Id))
                    .Keyword(k => k.Name(x => x.Dataset))
                    .Keyword(k => k.Name(x => x.NodeType))
                    .Keyword(k => k.Name(x => x.OntologyType))
                    .Keyword(k => k.Name(x => x.OperationalRole))
                    .Keyword(k => k.Name(x => x.EntityId))
                    .Keyword(k => k.Name(x => x.PerformerEntityIds))
                    .Keyword(k => k.Name(x => x.TargetEntityIds))
                    .Keyword(k => k.Name(x => x.RecipientEntityIds))
                    .Keyword(k => k.Name(x => x.Timestamp))
                    .Text(t => t.Name(x => x.Name))
                    .Text(t => t.Name(x => x.Location))
                    .Text(t => t.Name(x => x.Action))
                    .Text(t => t.Name(x => x.ActionObject))
                    .Text(t => t.Name(x => x.DirectResult))
                    .Text(t => t.Name(x => x.UpdatedState))
                    .Text(t => t.Name(x => x.SourceBasis))
                    .Text(t => t.Name(x => x.StaticProps))
                    .Text(t => t.Name(x => x.Content)))));

        if (!response.IsValid)
            throw new InvalidOperationException(
                $"Unable to create {IndexName}: {response.ServerError?.Error?.Reason ?? response.OriginalException?.Message}");
    }

    public async Task<int> IndexDatasetAsync(MilitaryDataset dataset, CancellationToken cancellationToken = default)
    {
        var documents = new List<CausalSearchDocument>();

        documents.AddRange(dataset.Entities.Select(e => new CausalSearchDocument
        {
            Id = $"entity:{e.Id}",
            Dataset = dataset.Id,
            NodeType = "Entity",
            EntityId = e.Id,
            Name = e.Name,
            OntologyType = e.OntologyType,
            OperationalRole = e.OperationalRole,
            StaticProps = System.Text.Json.JsonSerializer.Serialize(e.StaticProps),
            Content = $"{e.Name} {e.OntologyType} {e.OperationalRole} {string.Join(" ", e.StaticProps.Values)}"
        }));

        documents.AddRange(dataset.Actions.Select(a => new CausalSearchDocument
        {
            Id = $"action:{a.Id}",
            Dataset = dataset.Id,
            NodeType = "ActionNode",
            PerformerEntityIds = string.Join(",", a.PerformerEntityIds),
            TargetEntityIds = string.Join(",", a.TargetEntityIds),
            RecipientEntityIds = string.Join(",", a.RecipientEntityIds),
            Name = a.Name,
            OperationalRole = a.ActionType,
            Timestamp = a.Timestamp,
            Location = a.Location,
            Action = a.Name,
            ActionObject = a.ActionObject,
            DirectResult = a.DirectResult,
            Sequence = a.Sequence,
            Content = $"{a.Timestamp} {a.Location} {a.Name} {a.ActionObject} {a.DirectResult}"
        }));

        documents.AddRange(dataset.States.Select(s => new CausalSearchDocument
        {
            Id = $"state:{s.Id}",
            Dataset = dataset.Id,
            NodeType = "StateNode",
            EntityId = s.EntityId,
            Timestamp = s.Timestamp,
            Location = s.Location,
            Action = s.Action,
            ActionObject = s.ActionObject,
            DirectResult = s.DirectResult,
            UpdatedState = s.UpdatedState,
            SourceBasis = s.SourceBasis,
            Sequence = s.Sequence,
            Latitude = s.Latitude,
            Longitude = s.Longitude,
            Content = $"{s.Timestamp} {s.Location} {s.Action} {s.ActionObject} {s.DirectResult} {s.UpdatedState}"
        }));

        var indexed = 0;
        foreach (var document in documents)
        {
            var response = await _client.IndexAsync(document, i => i.Index(IndexName).Id(document.Id));
            if (!response.IsValid)
                throw new InvalidOperationException(
                    $"OpenSearch indexing failed for {document.Id}: {response.ServerError?.Error?.Reason ?? response.OriginalException?.Message}");
            indexed++;
        }

        _logger.LogInformation("Indexed {Count} causal documents into {Index}", indexed, IndexName);
        return indexed;
    }

    private sealed class CausalSearchDocument
    {
        public required string Id { get; init; }
        public required string Dataset { get; init; }
        public required string NodeType { get; init; }
        public string? EntityId { get; init; }
        public string? PerformerEntityIds { get; init; }
        public string? TargetEntityIds { get; init; }
        public string? RecipientEntityIds { get; init; }
        public string? Name { get; init; }
        public string? OntologyType { get; init; }
        public string? OperationalRole { get; init; }
        public string? Timestamp { get; init; }
        public string? Location { get; init; }
        public string? Action { get; init; }
        public string? ActionObject { get; init; }
        public string? DirectResult { get; init; }
        public string? UpdatedState { get; init; }
        public string? SourceBasis { get; init; }
        public string? StaticProps { get; init; }
        public int? Sequence { get; init; }
        public double? Latitude { get; init; }
        public double? Longitude { get; init; }
        public string? Content { get; init; }
    }
}
