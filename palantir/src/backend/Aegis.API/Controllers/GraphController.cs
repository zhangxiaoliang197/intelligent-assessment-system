using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class GraphController(IAegisService aegis) : ControllerBase
{
    [HttpGet("explore/{nodeId}")]
    [ProducesResponseType<GraphDto>(200)]
    public async Task<IActionResult> Explore(
        string nodeId,
        [FromQuery] int depth = 2,
        [FromQuery] string? excludeLabels = null,
        CancellationToken ct = default)
    {
        var exclude = excludeLabels?.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        var result = await aegis.ExploreGraphAsync(nodeId, depth, exclude, ct);
        return Ok(result);
    }

    [HttpPost("link-analysis")]
    [ProducesResponseType<LinkAnalysisDto>(200)]
    public async Task<IActionResult> LinkAnalysis([FromBody] LinkAnalysisRequest request, CancellationToken ct = default)
    {
        if (request.NodeIds is null || request.NodeIds.Count < 2)
            return BadRequest("At least 2 node IDs are required for link analysis.");

        var result = await aegis.FindHiddenLinksAsync(request.NodeIds, request.MaxDepth ?? 6, ct);
        return Ok(result);
    }
}

public record LinkAnalysisRequest(List<string> NodeIds, int? MaxDepth = 6);
