using Aegis.Application.Interfaces;
using Aegis.Domain.Interfaces;
using Aegis.Infrastructure.AI;
using Aegis.Infrastructure.Neo4j;
using Aegis.Infrastructure.Search;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aegis.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        // Neo4j
        services.AddSingleton<IGraphRepository, Neo4jGraphRepository>();
        services.AddSingleton<ICausalRepository, Neo4jCausalRepository>();
        services.AddSingleton<IDynamicOntologyRepository, DynamicOntologyRepository>();

        // OpenSearch
        services.AddSingleton<ISearchService, OpenSearchSearchService>();
        services.AddSingleton<ICausalSearchIndexer, OpenSearchCausalIndexer>();

        // Redis
        services.AddStackExchangeRedisCache(options =>
        {
            options.Configuration = configuration["ConnectionStrings:Redis"] ?? "localhost:6379";
            options.InstanceName = "aegis_";
        });

        // AI Services
        services.AddSingleton<IOllamaService, DeepSeekLlmService>();
        
        // 修正：指向 Application 层的 IOntologyAgentService
        services.AddSingleton<Aegis.Application.Interfaces.IOntologyAgentService, DeepSeekOntologyAgent>();
        
        services.AddScoped<IAgentService, AgentService>();
        services.AddScoped<ICommandCenterService, CommandCenterService>();
        services.AddScoped<IRiskPropagationService, RiskPropagationService>();

        // Application Services
        services.AddScoped<IAegisService, Aegis.Application.Services.AegisService>();
        return services;
    }
}