using Aegis.Application.Interfaces;
using Aegis.Domain.Entities;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Aegis.Infrastructure.AI;

public sealed class DeepSeekOntologyAgent : IOntologyAgentService
{
    private readonly IConfiguration _configuration;
    private readonly ILogger<DeepSeekOntologyAgent> _logger;
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMinutes(3) };

    public DeepSeekOntologyAgent(IConfiguration configuration, ILogger<DeepSeekOntologyAgent> logger)
    {
        _configuration = configuration;
        _logger = logger;
    }

    public bool IsConfigured => !string.IsNullOrWhiteSpace(GetApiKey());

    public async Task<OntologyProposal> ProposeAsync(
        OntologyAgentContext context,
        OntologyAgentRequest request,
        CancellationToken cancellationToken = default)
    {
        var apiKey = GetApiKey();
        if (string.IsNullOrWhiteSpace(apiKey))
            throw new InvalidOperationException("DeepSeek API 未配置。请在服务端环境变量 DEEPSEEK_API_KEY 中设置新的 Key，切勿写入 Vue 前端。 ");

        var baseUrl = (_configuration["DeepSeek:BaseUrl"] ??
                       _configuration["DEEPSEEK_BASE_URL"] ??
                       "https://api.deepseek.com").Trim().TrimEnd('/');
        var model = _configuration["DeepSeek:Model"] ??
                    _configuration["DEEPSEEK_MODEL"] ??
                    "deepseek-chat";
        var contextJson = JsonSerializer.Serialize(context, new JsonSerializerOptions { WriteIndented = true });

        var systemPrompt = """
你是 AEGIS 的 Ontology_Resolution_Agent。你的职责不是抽取已有实体，而是判断“当前本体表达能力是否不足”，并提出一个最小、可审计的本体扩充建议。

必须遵守：
1. 图数据库是事实源，不得编造现有节点、关系或证据。
2. 只允许提出 NEW_CLASS、NEW_RELATION、NEW_RULE 三类建议。
3. 一次只提出一个最有价值的建议；若没有必要扩充，仍可提出保守的 NEW_RULE，但必须明确证据不足。
4. 不得直接修改数据库，输出仅是 PROPOSED 草案，必须经人工批准。
5. confidence 必须在 0~1；evidence 只能引用输入上下文中确实存在的类型、关系、样例或规则。
6. 输出严格 JSON，不要 Markdown，不要代码围栏。

JSON 结构：
{
  "proposalType":"NEW_CLASS|NEW_RELATION|NEW_RULE",
  "name":"英文或领域稳定名称",
  "parentClass":"父类；非 NEW_CLASS 可为 null",
  "description":"中文说明",
  "confidence":0.0,
  "evidence":["证据1","证据2"]
}
""";

        var userPrompt = $"""
当前动态本体上下文：
{contextJson}

分析目标：
{request.Focus}

请仅返回一个 JSON 对象。
""";

        using var httpRequest = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/chat/completions");
        httpRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        var payload = new
        {
            model,
            temperature = 0.2,
            response_format = new { type = "json_object" },
            messages = new object[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        };
        httpRequest.Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

        using var response = await Http.SendAsync(httpRequest, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            _logger.LogWarning("DeepSeek ontology agent failed: {Status} {Body}", response.StatusCode, body);
            throw new InvalidOperationException($"DeepSeek 请求失败：{(int)response.StatusCode}");
        }

        using var envelope = JsonDocument.Parse(body);
        var content = envelope.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString();
        if (string.IsNullOrWhiteSpace(content)) throw new InvalidOperationException("DeepSeek 未返回本体建议。");

        using var proposalJson = JsonDocument.Parse(content);
        var root = proposalJson.RootElement;
        var type = root.GetProperty("proposalType").GetString() ?? "NEW_RULE";
        if (type is not ("NEW_CLASS" or "NEW_RELATION" or "NEW_RULE")) type = "NEW_RULE";
        var evidence = root.TryGetProperty("evidence", out var ev) && ev.ValueKind == JsonValueKind.Array
            ? ev.EnumerateArray().Select(x => x.GetString()).Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => x!).Take(10).ToArray()
            : [];
        var confidence = root.TryGetProperty("confidence", out var conf) && conf.TryGetDouble(out var score) ? Math.Clamp(score, 0, 1) : 0.5;

        return new OntologyProposal
        {
            Id = $"PROP-{DateTimeOffset.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid().ToString("N")[..6].ToUpperInvariant()}",
            ProposalType = type,
            Name = root.GetProperty("name").GetString() ?? "UnnamedProposal",
            ParentClass = root.TryGetProperty("parentClass", out var parent) && parent.ValueKind != JsonValueKind.Null ? parent.GetString() : null,
            Description = root.GetProperty("description").GetString() ?? "",
            Confidence = confidence,
            Evidence = evidence,
            Status = "PROPOSED",
            CreatedAt = DateTimeOffset.UtcNow
        };
    }

    private string? GetApiKey() =>
        (_configuration["DeepSeek:ApiKey"] ?? _configuration["DEEPSEEK_API_KEY"])?.Trim();
}
