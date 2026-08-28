using Aegis.Domain.Entities;
using Microsoft.AspNetCore.SignalR;

namespace Aegis.API.Hubs;

public class AlertHub : Hub
{
    public override async Task OnConnectedAsync()
    {
        await Clients.Caller.SendAsync("Connected", new
        {
            message = "Connected to AEGIS Intelligence Platform",
            timestamp = DateTime.UtcNow
        });
        await base.OnConnectedAsync();
    }

    public async Task SubscribeToFacility(string facilityId)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, $"facility_{facilityId}");
        await Clients.Caller.SendAsync("Subscribed", new { facilityId });
    }

    public async Task SubscribeToCriticalAlerts()
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, "critical_alerts");
        await Clients.Caller.SendAsync("Subscribed", new { channel = "critical_alerts" });
    }

    public async Task SubscribeToOntology()
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, "dynamic_ontology");
        await Clients.Caller.SendAsync("Subscribed", new { channel = "dynamic_ontology" });
    }
}

public class AlertNotificationService(IHubContext<AlertHub> hubContext)
{
    public async Task NotifyNewEventAsync(string eventId, string eventType, int severity, string? facilityId)
    {
        var alert = new { eventId, eventType, severity, facilityId, timestamp = DateTime.UtcNow };
        if (severity >= 4)
            await hubContext.Clients.Group("critical_alerts").SendAsync("CriticalAlert", alert);
        if (facilityId != null)
            await hubContext.Clients.Group($"facility_{facilityId}").SendAsync("FacilityAlert", alert);
        await hubContext.Clients.All.SendAsync("NewEvent", alert);
    }

    public async Task NotifyNewRiskCaseAsync(string caseId, string title, double riskScore) =>
        await hubContext.Clients.All.SendAsync("NewRiskCase", new { caseId, title, riskScore, timestamp = DateTime.UtcNow });

    public async Task NotifyOntologyMutationAsync(OntologyMutation mutation) =>
        await hubContext.Clients.Group("dynamic_ontology").SendAsync("OntologyMutation", mutation);
}
