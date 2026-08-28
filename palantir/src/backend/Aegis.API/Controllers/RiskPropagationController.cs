using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

/// <summary>
/// Risk Propagation — calculates blast radius ("shockwave") from any compromised node
/// through the knowledge graph with exponential decay.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class RiskPropagationController(
    IRiskPropagationService propagation,
    ILogger<RiskPropagationController> logger) : ControllerBase
{
    /// <summary>
    /// Calculate risk propagation from a source node.
    /// Returns waves of diminishing risk with affected nodes and a graph for visualization.
    /// </summary>
    [HttpPost("propagate")]
    [ProducesResponseType<RiskPropagationResult>(200)]
    public async Task<IActionResult> Propagate(
        [FromBody] RiskPropagationRequest request,
        CancellationToken ct = default)
    {
        try
        {
            var result = await propagation.PropagateRiskAsync(
                request.SourceNodeId,
                request.MaxDepth,
                request.DecayFactor,
                ct);

            return Ok(result);
        }
        catch (InvalidOperationException ex)
        {
            return NotFound(new { error = ex.Message });
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Risk propagation failed for {NodeId}", request.SourceNodeId);
            return StatusCode(500, new { error = ex.Message });
        }
    }
}
