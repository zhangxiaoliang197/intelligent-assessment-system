using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class TimelineController(IAegisService aegis) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<IEnumerable<TimelineEventDto>>(200)]
    public async Task<IActionResult> Get(
        [FromQuery] DateTime from,
        [FromQuery] DateTime to,
        [FromQuery] string? facilityId,
        CancellationToken ct)
    {
        var result = await aegis.GetTimelineAsync(from, to, facilityId, ct);
        return Ok(result);
    }
}
