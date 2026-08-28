using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class DashboardController(IAegisService aegis) : ControllerBase
{
    [HttpGet("stats")]
    [ProducesResponseType<DashboardStatsDto>(200)]
    public async Task<IActionResult> GetStats(CancellationToken ct)
    {
        var result = await aegis.GetDashboardStatsAsync(ct);
        return Ok(result);
    }
}
