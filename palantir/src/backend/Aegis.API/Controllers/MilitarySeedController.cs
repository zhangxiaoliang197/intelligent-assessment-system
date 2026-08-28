using Aegis.API.Contracts;
using Aegis.API.SeedData;
using Aegis.Domain.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/seed")]
public sealed class MilitarySeedController(
    ICausalRepository repository,
    ICausalSearchIndexer searchIndexer,
    ILogger<MilitarySeedController> logger) : ControllerBase
{
    [HttpPost("military-dataset")]
    public async Task<ActionResult<MilitarySeedResponseDto>> SeedMilitaryDataset(CancellationToken cancellationToken)
    {
        var dataset = MilitaryDatasetSeed.Create();
        var graphResult = await repository.SeedMilitaryDatasetAsync(dataset, cancellationToken);
        await searchIndexer.EnsureIndexAsync(cancellationToken);
        var searchDocuments = await searchIndexer.IndexDatasetAsync(dataset, cancellationToken);

        logger.LogInformation("Military causal dataset {DatasetId} initialized", dataset.Id);
        return Ok(new MilitarySeedResponseDto(
            dataset.Id,
            graphResult.EntityCount,
            graphResult.ActionCount,
            graphResult.StateCount,
            graphResult.RelationshipCount,
            searchDocuments,
            "Military causal dataset initialized in Neo4j and OpenSearch."));
    }
}
