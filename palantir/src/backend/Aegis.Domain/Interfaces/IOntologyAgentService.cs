using Aegis.Domain.Entities;

namespace Aegis.Domain.Interfaces;

public interface IOntologyAgentService
{
    Task<IReadOnlyList<OntologyProposal>> DiscoverAsync(CancellationToken cancellationToken = default);
}
