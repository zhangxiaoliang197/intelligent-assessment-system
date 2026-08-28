using Aegis.Application.DTOs;
using Aegis.Application.Interfaces;
using Aegis.API.Contracts;
using Aegis.API.Hubs;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class EventsController(IAegisService aegis, AlertNotificationService notifier) : ControllerBase
{
    [HttpGet]
    [ProducesResponseType<IEnumerable<EventDto>>(200)]
    public async Task<IActionResult> GetAll(
        [FromQuery] string? eventType,
        [FromQuery] int? minSeverity,
        [FromQuery] int? severity,
        [FromQuery] string? facilityId,
        [FromQuery] DateTime? from,
        [FromQuery] DateTime? to,
        CancellationToken ct)
    {
        var result = await aegis.GetEventsAsync(eventType, minSeverity, severity, facilityId, from, to, ct);
        return Ok(result);
    }

    [HttpPost("ingest")]
    [ProducesResponseType<EventDto>(200)]
    public async Task<IActionResult> Ingest([FromBody] IngestEventRequest request, CancellationToken ct)
    {
        var result = await aegis.IngestEventAsync(
            request.EventType, request.Description, request.Severity,
            request.FacilityId, request.PersonId, request.Metadata, ct);

        await notifier.NotifyNewEventAsync(
            result.EventId, result.EventType, result.Severity, result.FacilityId);

        return Ok(result);
    }
}
