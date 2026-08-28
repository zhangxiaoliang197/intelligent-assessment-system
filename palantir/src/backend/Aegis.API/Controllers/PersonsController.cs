using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class PersonsController(IAegisService aegis) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<IEnumerable<PersonDto>>(200)]
    public async Task<IActionResult> GetAll(CancellationToken ct)
    {
        var result = await aegis.GetPersonsAsync(ct);
        return Ok(result);
    }
}
