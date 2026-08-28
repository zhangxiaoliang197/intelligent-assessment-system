using Aegis.API.Hubs;
using Aegis.Application.Interfaces;
using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.AspNetCore.Mvc;

// 显式指定别名，解决 Aegis.Application 与 Aegis.Domain 同名接口冲突
using IOntologyAgentService = Aegis.Application.Interfaces.IOntologyAgentService;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/dynamic-ontology")]
public sealed class DynamicOntologyController(
    IDynamicOntologyRepository repository,
    IOntologyAgentService agent,
    AlertNotificationService notifier) : ControllerBase
{
    [HttpGet("graph")]
    public async Task<ActionResult<CausalGraphResult>> Graph(CancellationToken ct) =>
        Ok(await repository.GetDynamicGraphAsync(ct));

    [HttpGet("statistics")]
    public async Task<ActionResult<DynamicOntologyStatistics>> Statistics(CancellationToken ct) =>
        Ok(await repository.GetStatisticsAsync(ct));

    [HttpGet("rules")]
    public async Task<ActionResult<IReadOnlyList<OntologyRuleDescriptor>>> Rules(CancellationToken ct) =>
        Ok(await repository.GetRulesAsync(ct));

    [HttpPost("run")]
    public async Task<ActionResult<DynamicOntologyRunResult>> Run(CancellationToken ct)
    {
        var result = await repository.RunDerivationRulesAsync(ct);
        foreach (var mutation in result.Mutations)
            await notifier.NotifyOntologyMutationAsync(mutation);
        return Ok(result);
    }

    [HttpGet("resolution-candidates")]
    public async Task<ActionResult<IReadOnlyList<ResolutionCandidate>>> ResolutionCandidates(CancellationToken ct) =>
        Ok(await repository.FindResolutionCandidatesAsync(ct));

    [HttpPost("merge")]
    public async Task<ActionResult<OntologyMutation>> Merge([FromBody] MergeNodesRequest request, CancellationToken ct)
    {
        try
        {
            var mutation = await repository.MergeNodesAsync(request, ct);
            await notifier.NotifyOntologyMutationAsync(mutation);
            return Ok(mutation);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException)
        {
            return BadRequest(new { message = ex.Message });
        }
    }

    [HttpGet("mutations")]
    public async Task<ActionResult<IReadOnlyList<OntologyMutation>>> Mutations([FromQuery] int limit = 50, CancellationToken ct = default) =>
        Ok(await repository.GetMutationsAsync(limit, ct));

    [HttpPost("entities")]
    public async Task<ActionResult<ManualOntologyNodeResult>> CreateEntity([FromBody] ManualOntologyNodeRequest request, CancellationToken ct)
    {
        try
        {
            var created = await repository.CreateManualNodeAsync(request, ct);
            var mutation = (await repository.GetMutationsAsync(1, ct)).FirstOrDefault();
            if (mutation is not null) await notifier.NotifyOntologyMutationAsync(mutation);
            return Created($"/api/dynamic-ontology/graph#{created.Id}", created);
        }
        catch (ArgumentException ex)
        {
            return BadRequest(new { message = ex.Message });
        }
    }

    [HttpPost("relationships")]
    public async Task<ActionResult<OntologyMutation>> CreateRelationship([FromBody] ManualOntologyRelationRequest request, CancellationToken ct)
    {
        try
        {
            var mutation = await repository.CreateManualRelationAsync(request, ct);
            await notifier.NotifyOntologyMutationAsync(mutation);
            return Ok(mutation);
        }
        catch (ArgumentException ex)
        {
            return BadRequest(new { message = ex.Message });
        }
    }

    [HttpGet("agent/status")]
    public ActionResult AgentStatus() => Ok(new { configured = agent.IsConfigured });

    [HttpPost("agent/propose")]
    public async Task<ActionResult<OntologyProposal>> AgentPropose([FromBody] OntologyAgentRequest request, CancellationToken ct)
    {
        if (!agent.IsConfigured)
            return StatusCode(StatusCodes.Status503ServiceUnavailable, new { message = "DeepSeek API 未在服务端配置。" });
        try
        {
            var context = await repository.BuildAgentContextAsync(ct);
            var proposal = await agent.ProposeAsync(context, request, ct);
            await repository.SaveProposalAsync(proposal, ct);
            var mutation = (await repository.GetMutationsAsync(1, ct)).FirstOrDefault();
            if (mutation is not null) await notifier.NotifyOntologyMutationAsync(mutation);
            return Ok(proposal);
        }
        catch (Exception ex)
        {
            return StatusCode(StatusCodes.Status502BadGateway, new { message = ex.Message });
        }
    }

    [HttpGet("proposals")]
    public async Task<ActionResult<IReadOnlyList<OntologyProposal>>> Proposals([FromQuery] string? status = null, CancellationToken ct = default) =>
        Ok(await repository.GetProposalsAsync(status, ct));

    [HttpPost("proposals/{proposalId}/approve")]
    public async Task<ActionResult<OntologyMutation>> ApproveProposal(string proposalId, CancellationToken ct)
    {
        try
        {
            var mutation = await repository.ApproveProposalAsync(proposalId, ct);
            await notifier.NotifyOntologyMutationAsync(mutation);
            return Ok(mutation);
        }
        catch (InvalidOperationException ex)
        {
            return NotFound(new { message = ex.Message });
        }
    }
}