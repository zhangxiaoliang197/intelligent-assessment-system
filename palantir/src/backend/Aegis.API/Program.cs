using Aegis.API.Hubs;
using Aegis.API.Services;
using Aegis.Application.Interfaces;
using Aegis.Domain.Interfaces;
using Aegis.Infrastructure;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console(outputTemplate: "[{Timestamp:HH:mm:ss} {Level:u3}] {Message:lj}{NewLine}{Exception}")
    .CreateLogger();

builder.Host.UseSerilog();
builder.Services.AddInfrastructure(builder.Configuration);
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c => c.SwaggerDoc("v1", new() { Title = "AEGIS Intelligence API", Version = "v1" }));
builder.Services.AddSignalR();

builder.Services.AddSingleton<AlertNotificationService>();
builder.Services.AddSingleton<InferenceEngine>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<InferenceEngine>());
builder.Services.AddHostedService<SearchReindexService>();

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.WithOrigins("http://localhost:3000", "http://localhost:5173")
              .AllowAnyHeader()
              .AllowAnyMethod()
              .AllowCredentials();
    });
});

var app = builder.Build();
app.UseSerilogRequestLogging();
app.UseCors();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI(c => c.SwaggerEndpoint("/swagger/v1/swagger.json", "AEGIS v1"));
}

app.MapControllers();
app.MapHub<AlertHub>("/hub/alerts");

using (var scope = app.Services.CreateScope())
{
    var searchService = scope.ServiceProvider.GetRequiredService<Aegis.Domain.Interfaces.ISearchService>();
    try
    {
        await searchService.EnsureIndexAsync();
    }
    catch (Exception ex)
    {
        Log.Warning(ex, "Could not initialize Elasticsearch index – search may be unavailable");
    }

    try
    {
        var ontology = scope.ServiceProvider.GetRequiredService<IDynamicOntologyRepository>();
        await ontology.EnsureSchemaAsync();
    }
    catch (Exception ex)
    {
        Log.Warning(ex, "Could not initialize dynamic ontology schema – engine will retry in background");
    }
}

Log.Information("☁️ AI provider: DeepSeek cloud API (no local model container)");

Log.Information("🛰️ AEGIS Intelligence Platform starting...");
app.Run();
