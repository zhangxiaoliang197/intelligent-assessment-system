using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class SearchController(IAegisService aegis) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<SearchResultDto>(200)]
    public async Task<IActionResult> Search([FromQuery] string q, [FromQuery] int page = 1, CancellationToken ct = default)
    {
        var result = await aegis.SearchAsync(q, page, ct: ct);
        return Ok(result);
    }
}
