using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class RiskCasesController(IAegisService aegis) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<IEnumerable<RiskCaseDto>>(200)]
    public async Task<IActionResult> GetAll(CancellationToken ct)
    {
        var result = await aegis.GetRiskCasesAsync(ct);
        return Ok(result);
    }

    [HttpGet("{caseId}/graph")]
    [ProducesResponseType<GraphDto>(200)]
    public async Task<IActionResult> GetCaseGraph(string caseId, CancellationToken ct)
    {
        var result = await aegis.GetCaseGraphAsync(caseId, ct);
        return Ok(result);
    }
}
