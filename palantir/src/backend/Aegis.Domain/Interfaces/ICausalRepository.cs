using Aegis.Domain.Entities;

namespace Aegis.Domain.Interfaces;

public interface ICausalRepository
{
    Task<MilitarySeedResult> SeedMilitaryDatasetAsync(MilitaryDataset dataset, CancellationToken cancellationToken = default);
    Task<CausalGraphResult> GetOverviewAsync(CancellationToken cancellationToken = default);
    Task<CausalGraphResult> TraceBackAsync(string targetEntityId, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<EntityTimelinePoint>> GetEntityTimelineAsync(string entityId, CancellationToken cancellationToken = default);
    Task<CausalStatistics> GetStatisticsAsync(CancellationToken cancellationToken = default);
}
