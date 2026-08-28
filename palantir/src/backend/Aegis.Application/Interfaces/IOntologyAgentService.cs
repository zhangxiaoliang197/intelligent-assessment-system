using Aegis.Domain.Entities;

namespace Aegis.Application.Interfaces;

public interface IOntologyAgentService
{
    bool IsConfigured { get; }
    Task<OntologyProposal> ProposeAsync(OntologyAgentContext context, OntologyAgentRequest request, CancellationToken cancellationToken = default);
}
