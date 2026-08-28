using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class FacilitiesController(IAegisService aegis) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<IEnumerable<FacilityDto>>(200)]
    public async Task<IActionResult> GetAll(CancellationToken ct)
    {
        var result = await aegis.GetFacilitiesAsync(ct);
        return Ok(result);
    }
}
