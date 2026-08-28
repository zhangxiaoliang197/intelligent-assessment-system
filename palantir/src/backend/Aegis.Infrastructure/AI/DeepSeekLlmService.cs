using Aegis.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace Aegis.Infrastructure.AI;

/// <summary>
/// OpenAI-compatible DeepSeek cloud client used by the existing AEGIS agent stack.
/// Despite the legacy IOllamaService interface name in the upstream project, this
/// implementation does not contact Ollama and does not require any local model.
/// </summary>
public sealed class DeepSeekLlmService : IOllamaService
{
    private readonly HttpClient _http;
    private readonly ILogger<DeepSeekLlmService> _logger;
    private readonly string _model;
    private readonly string _apiKey;

    public DeepSeekLlmService(IConfiguration configuration, ILogger<DeepSeekLlmService> logger)
    {
        _logger = logger;
        _apiKey = (configuration["DeepSeek:ApiKey"] ?? configuration["DEEPSEEK_API_KEY"] ?? string.Empty).Trim();
        _model = configuration["DeepSeek:Model"] ?? configuration["DEEPSEEK_MODEL"] ?? "deepseek-chat";
        var baseUrl = (configuration["DeepSeek:BaseUrl"] ??
                       configuration["DEEPSEEK_BASE_URL"] ??
                       "https://api.deepseek.com").Trim().TrimEnd('/') + "/";

        _http = new HttpClient
        {
            BaseAddress = new Uri(baseUrl),
            Timeout = TimeSpan.FromMinutes(3)
        };
    }

    /// <summary>
    /// Kept only for compatibility with the upstream interface. Cloud APIs do not
    /// require model download or warm-up, so this is intentionally a no-op.
    /// </summary>
    public Task EnsureModelAsync(CancellationToken ct = default)
    {
        EnsureConfigured();
        return Task.CompletedTask;
    }

    public async Task<string> GenerateAsync(
        string systemPrompt,
        string userPrompt,
        CancellationToken ct = default)
    {
        EnsureConfigured();

        using var request = new HttpRequestMessage(HttpMethod.Post, "chat/completions");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        request.Content = JsonContent(new
        {
            model = _model,
            temperature = 0.3,
            stream = false,
            messages = new object[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        });

        using var response = await _http.SendAsync(request, ct);
        var body = await response.Content.ReadAsStringAsync(ct);
        if (!response.IsSuccessStatusCode)
        {
            _logger.LogWarning("DeepSeek generation failed: {Status} {Body}", response.StatusCode, body);
            throw new InvalidOperationException($"DeepSeek 请求失败：{(int)response.StatusCode}");
        }

        using var json = JsonDocument.Parse(body);
        return json.RootElement
                   .GetProperty("choices")[0]
                   .GetProperty("message")
                   .GetProperty("content")
                   .GetString()
               ?? string.Empty;
    }

    public async IAsyncEnumerable<string> StreamAsync(
        string systemPrompt,
        string userPrompt,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        EnsureConfigured();

        using var request = new HttpRequestMessage(HttpMethod.Post, "chat/completions");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        request.Content = JsonContent(new
        {
            model = _model,
            temperature = 0.3,
            stream = true,
            messages = new object[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        });

        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(ct);
            _logger.LogWarning("DeepSeek stream failed: {Status} {Body}", response.StatusCode, body);
            throw new InvalidOperationException($"DeepSeek 流式请求失败：{(int)response.StatusCode}");
        }

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream);

        while (!ct.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(ct);
            if (line is null) yield break;
            if (string.IsNullOrWhiteSpace(line) || !line.StartsWith("data:", StringComparison.OrdinalIgnoreCase))
                continue;

            var payload = line[5..].Trim();
            if (payload == "[DONE]") yield break;

            string? token = null;
            try
            {
                using var json = JsonDocument.Parse(payload);
                var root = json.RootElement;
                if (root.TryGetProperty("choices", out var choices) && choices.GetArrayLength() > 0)
                {
                    var delta = choices[0].GetProperty("delta");
                    if (delta.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.String)
                        token = content.GetString();
                }
            }
            catch (JsonException ex)
            {
                _logger.LogDebug(ex, "Ignoring malformed DeepSeek SSE chunk");
            }

            if (!string.IsNullOrEmpty(token))
                yield return token;
        }
    }

    private void EnsureConfigured()
    {
        if (string.IsNullOrWhiteSpace(_apiKey))
            throw new InvalidOperationException(
                "DeepSeek API 未配置。请仅在服务器端 .env 中设置 DEEPSEEK_API_KEY，不要把 Key 写入 Vue 前端。"
            );
    }

    private static StringContent JsonContent(object payload) =>
        new(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
}
