using Microsoft.AspNetCore.SignalR;

namespace Aegis.API.Hubs;

public sealed class OntologyHub : Hub
{
    public override async Task OnConnectedAsync()
    {
        await Clients.Caller.SendAsync("OntologyConnected", new { timestamp = DateTimeOffset.UtcNow });
        await base.OnConnectedAsync();
    }
}

public sealed class OntologyNotificationService(IHubContext<OntologyHub> hub)
{
    public Task PublishAsync(object mutation, CancellationToken cancellationToken = default) =>
        hub.Clients.All.SendAsync("OntologyMutation", mutation, cancellationToken);
}
