using Aegis.API.Contracts;
using Aegis.Domain.Entities;
using Aegis.Domain.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace Aegis.API.Controllers;

[ApiController]
[Route("api/causal")]
public sealed class CausalController(ICausalRepository repository) : ControllerBase
{
    [HttpGet("overview")]
    public async Task<ActionResult<CausalGraphDto>> GetOverview(CancellationToken cancellationToken)
        => Ok((await repository.GetOverviewAsync(cancellationToken)).ToDto());

    [HttpGet("statistics")]
    public async Task<ActionResult<CausalStatisticsDto>> GetStatistics(CancellationToken cancellationToken)
        => Ok((await repository.GetStatisticsAsync(cancellationToken)).ToDto());

    [HttpGet("trace-back")]
    public async Task<ActionResult<CausalGraphDto>> TraceBack(
        [FromQuery] string targetEntityId,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(targetEntityId))
            return BadRequest(new { message = "targetEntityId is required." });

        var graph = await repository.TraceBackAsync(targetEntityId, cancellationToken);
        if (graph.Nodes.Count == 0)
            return NotFound(new { message = $"No causal chain found for entity '{targetEntityId}'." });
        return Ok(graph.ToDto());
    }

    [HttpGet("entity-timeline/{entityId}")]
    public async Task<ActionResult<IReadOnlyList<EntityTimelinePointDto>>> GetTimeline(
        string entityId,
        CancellationToken cancellationToken)
    {
        var timeline = await repository.GetEntityTimelineAsync(entityId, cancellationToken);
        if (timeline.Count == 0)
            return NotFound(new { message = $"No timeline found for entity '{entityId}'." });
        return Ok(timeline.Select(x => x.ToDto()).ToArray());
    }

    [HttpPost("attribution")]
    public async Task<ActionResult<CausalAttributionDto>> Attribution(
        [FromBody] CausalAttributionRequest request,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(request.TargetEntityId))
            return BadRequest(new { message = "targetEntityId is required." });

        var graph = await repository.TraceBackAsync(request.TargetEntityId, cancellationToken);
        var target = graph.Nodes.FirstOrDefault(node => node.Id == request.TargetEntityId);
        if (target is null)
            return NotFound(new { message = $"No causal target found for '{request.TargetEntityId}'." });

        var actions = graph.Nodes.Where(node => node.Type == "ActionNode").ToDictionary(node => node.Id);
        var causalEdges = graph.Edges
            .Where(edge => edge.Type == "CAUSES" && actions.ContainsKey(edge.Source) && actions.ContainsKey(edge.Target))
            .ToArray();
        var terminalIds = graph.Edges
            .Where(edge => edge.Type == "TARGETS" && edge.Target == request.TargetEntityId && actions.ContainsKey(edge.Source))
            .Select(edge => edge.Source)
            .Distinct()
            .ToArray();

        var paths = EnumeratePaths(actions.Keys, causalEdges, terminalIds, Math.Clamp(request.MaxDepth, 1, 20));
        if (paths.Count == 0 && terminalIds.Length > 0)
            paths.AddRange(terminalIds.Select(id => new List<string> { id }));

        var pathWeights = paths
            .Select(path => new WeightedPath(path, 1.0 / (1.0 + Math.Max(0, path.Count - 1) * 0.15)))
            .ToArray();
        var totalContribution = pathWeights.Sum(path => path.Weight * path.NodeIds.Count);

        var actionItems = actions.Values
            .Select(action => CreateActionAttribution(action, pathWeights, totalContribution, request.IncludeCounterfactual))
            .Where(item => item.PathCount > 0)
            .OrderByDescending(item => item.ContributionPercent)
            .ToArray();

        var performerByAction = graph.Edges
            .Where(edge => edge.Type == "PERFORMS" && actions.ContainsKey(edge.Target))
            .GroupBy(edge => edge.Target)
            .ToDictionary(group => group.Key, group => group.Select(edge => edge.Source).Distinct().ToArray());
        var entityNodes = graph.Nodes.Where(node => node.Type == "Entity").ToDictionary(node => node.Id);
        var entityTotals = new Dictionary<string, (double Contribution, int Paths, bool Direct)>();
        foreach (var action in actionItems)
        {
            if (!performerByAction.TryGetValue(action.Id, out var performers) || performers.Length == 0)
                continue;
            foreach (var performerId in performers)
            {
                var current = entityTotals.GetValueOrDefault(performerId);
                entityTotals[performerId] = (
                    current.Contribution + action.ContributionPercent / performers.Length,
                    current.Paths + action.PathCount,
                    current.Direct || action.Direct);
            }
        }

        var entityItems = entityTotals
            .Where(item => entityNodes.ContainsKey(item.Key))
            .Select(item =>
            {
                var node = entityNodes[item.Key];
                var impact = CalculateImpact(pathWeights, path => path.NodeIds.Any(actionId =>
                    performerByAction.GetValueOrDefault(actionId)?.Contains(item.Key) == true));
                return new CausalAttributionItemDto(
                    node.Id, node.Label, node.Type, null, item.Value.Contribution,
                    request.IncludeCounterfactual ? impact : 0, item.Value.Paths, item.Value.Direct);
            })
            .OrderByDescending(item => item.ContributionPercent)
            .ToArray();

        var phaseItems = actionItems
            .GroupBy(item => item.Phase ?? "未标注阶段")
            .Select(group => new CausalAttributionItemDto(
                group.Key,
                group.Key,
                "Phase",
                group.Key,
                group.Sum(item => item.ContributionPercent),
                group.Sum(item => item.CounterfactualImpactPercent),
                group.Sum(item => item.PathCount),
                group.Any(item => item.Direct)))
            .OrderByDescending(item => item.ContributionPercent)
            .ToArray();

        var criticalNodes = actionItems
            .Where(item => request.IncludeCounterfactual && item.CounterfactualImpactPercent > 0)
            .OrderByDescending(item => item.CounterfactualImpactPercent)
            .Take(10)
            .Select(item => new CausalCounterfactualDto(
                item.Id, item.Name, item.CounterfactualImpactPercent,
                item.CounterfactualImpactPercent >= 99.99))
            .ToArray();

        var pathDtos = pathWeights
            .OrderByDescending(path => path.Weight)
            .Take(50)
            .Select(path => new CausalAttributionPathDto(
                path.NodeIds,
                path.NodeIds.Select(id => actions[id].Label).ToArray(),
                path.Weight))
            .ToArray();

        return Ok(new CausalAttributionDto(
            new CausalGraphNodeDto(target.Id, target.Label, target.Type, target.Category, target.Role, target.Properties),
            new CausalAttributionSummaryDto(
                actionItems.Length, entityItems.Length, phaseItems.Length,
                pathWeights.Length, criticalNodes.Length),
            actionItems, entityItems, phaseItems, pathDtos, criticalNodes));
    }

    private static CausalAttributionItemDto CreateActionAttribution(
        CausalGraphNode action,
        IReadOnlyList<WeightedPath> paths,
        double totalContribution,
        bool includeCounterfactual)
    {
        var matchingPaths = paths.Where(path => path.NodeIds.Contains(action.Id)).ToArray();
        var contribution = totalContribution <= 0
            ? 0
            : matchingPaths.Sum(path => path.Weight) / totalContribution * 100;
        var impact = includeCounterfactual ? CalculateImpact(paths, path => path.NodeIds.Contains(action.Id)) : 0;
        var phase = action.Properties.TryGetValue("timeNode", out var timeNode)
            ? $"阶段 {timeNode}"
            : action.Properties.TryGetValue("sequence", out var sequence) ? $"序列 {sequence}" : null;
        var direct = paths.Any(path => path.NodeIds.LastOrDefault() == action.Id);
        return new CausalAttributionItemDto(
            action.Id, action.Label, action.Type, phase, contribution, impact, matchingPaths.Length, direct);
    }

    private static double CalculateImpact(
        IReadOnlyList<WeightedPath> paths,
        Func<WeightedPath, bool> containsNode)
    {
        if (paths.Count == 0) return 0;
        var affected = paths.Count(containsNode);
        return affected * 100.0 / paths.Count;
    }

    private static List<List<string>> EnumeratePaths(
        IEnumerable<string> actionIds,
        IReadOnlyList<CausalGraphEdge> causalEdges,
        IReadOnlyList<string> terminalIds,
        int maxDepth)
    {
        var incoming = actionIds.ToDictionary(id => id, _ => new List<string>());
        foreach (var edge in causalEdges)
            incoming[edge.Target].Add(edge.Source);

        var result = new List<List<string>>();
        foreach (var terminalId in terminalIds)
            WalkUpstream(terminalId, incoming, [], new HashSet<string>(), maxDepth, result);
        return result;
    }

    private static void WalkUpstream(
        string current,
        IReadOnlyDictionary<string, List<string>> incoming,
        List<string> reversePath,
        HashSet<string> visited,
        int maxDepth,
        ICollection<List<string>> result)
    {
        if (reversePath.Count >= maxDepth || !visited.Add(current))
        {
            result.Add(reversePath.AsEnumerable().Reverse().ToList());
            return;
        }

        reversePath.Add(current);
        var parents = incoming.GetValueOrDefault(current);
        if (parents is null || parents.Count == 0)
        {
            result.Add(reversePath.AsEnumerable().Reverse().ToList());
        }
        else
        {
            foreach (var parent in parents)
                WalkUpstream(parent, incoming, reversePath, visited, maxDepth, result);
        }
        reversePath.RemoveAt(reversePath.Count - 1);
        visited.Remove(current);
    }

    private sealed record WeightedPath(IReadOnlyList<string> NodeIds, double Weight);
}
