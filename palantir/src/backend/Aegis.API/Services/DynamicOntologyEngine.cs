using Aegis.API.Hubs;
using Aegis.Domain.Interfaces;

namespace Aegis.API.Services;

/// <summary>
/// Dynamic ontology lifecycle engine. It periodically evaluates deterministic
/// derivation rules. Entity merges and Agent proposals remain human-controlled.
/// </summary>
public sealed class DynamicOntologyEngine(
    IServiceProvider services,
    ILogger<DynamicOntologyEngine> logger) : BackgroundService
{
    private readonly TimeSpan _interval = TimeSpan.FromSeconds(45);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation("Dynamic Ontology Engine started – rule evaluation every {Seconds}s", _interval.TotalSeconds);
        await Task.Delay(TimeSpan.FromSeconds(12), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var scope = services.CreateScope();
                var repo = scope.ServiceProvider.GetRequiredService<IDynamicOntologyRepository>();
                var notifier = scope.ServiceProvider.GetRequiredService<AlertNotificationService>();
                await repo.EnsureSchemaAsync(stoppingToken);
                var result = await repo.RunDerivationRulesAsync(stoppingToken);
                foreach (var mutation in result.Mutations)
                    await notifier.NotifyOntologyMutationAsync(mutation);
                if (result.CreatedNodeCount > 0)
                    logger.LogInformation("Dynamic ontology grew by {Count} derived nodes", result.CreatedNodeCount);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Dynamic ontology engine cycle failed");
            }

            await Task.Delay(_interval, stoppingToken);
        }
    }
}
