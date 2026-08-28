using Aegis.Domain.Entities;

namespace Aegis.Domain.Interfaces;

public interface ICausalSearchIndexer
{
    Task EnsureIndexAsync(CancellationToken cancellationToken = default);
    Task<int> IndexDatasetAsync(MilitaryDataset dataset, CancellationToken cancellationToken = default);
}
