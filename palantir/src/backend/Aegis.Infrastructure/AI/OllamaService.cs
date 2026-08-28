using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Aegis.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace Aegis.Infrastructure.AI;

/// <summary>
/// Client for Ollama HTTP API.  Supports both full-response and streaming generation.
/// </summary>
public sealed class OllamaService : IOllamaService
{
    private readonly HttpClient _http;
    private readonly string _model;
    private readonly ILogger<OllamaService> _logger;
    private bool _modelReady;

    public OllamaService(IConfiguration config, ILogger<OllamaService> logger)
    {
        _logger = logger;
        var baseUrl = config["Ollama:BaseUrl"] ?? "http://localhost:11434";
        _model = config["Ollama:Model"] ?? "phi3:mini";
        _http = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromMinutes(10) };
    }

    /// <inheritdoc />
    public async Task EnsureModelAsync(CancellationToken ct = default)
    {
        if (_modelReady) return;

        try
        {
            var tags = await _http.GetAsync("/api/tags", ct);
            if (tags.IsSuccessStatusCode)
            {
                var json = await tags.Content.ReadAsStringAsync(ct);
                if (json.Contains(_model.Split(':')[0], StringComparison.OrdinalIgnoreCase))
                {
                    _logger.LogInformation("🤖 Ollama model '{Model}' already available", _model);
                    _modelReady = true;
                    return;
                }
            }

            _logger.LogInformation("🤖 Pulling Ollama model '{Model}' – this may take a few minutes…", _model);
            var pullReq = new { name = _model, stream = false };
            var resp = await _http.PostAsJsonAsync("/api/pull", pullReq, ct);
            resp.EnsureSuccessStatusCode();
            _logger.LogInformation("🤖 Model '{Model}' pulled successfully", _model);
            _modelReady = true;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Could not pull Ollama model '{Model}' – AI features may be unavailable", _model);
        }
    }

    /// <inheritdoc />
    public async Task<string> GenerateAsync(string systemPrompt, string userPrompt, CancellationToken ct = default)
    {
        var payload = new OllamaRequest
        {
            Model = _model,
            System = systemPrompt,
            Prompt = userPrompt,
            Stream = false,
            Options = new OllamaOptions { Temperature = 0.4, NumCtx = 4096 }
        };

        var resp = await _http.PostAsJsonAsync("/api/generate", payload, ct);
        resp.EnsureSuccessStatusCode();
        var result = await resp.Content.ReadFromJsonAsync<OllamaResponse>(cancellationToken: ct);
        return result?.Response ?? string.Empty;
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<string> StreamAsync(
        string systemPrompt, string userPrompt,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var payload = new OllamaRequest
        {
            Model = _model,
            System = systemPrompt,
            Prompt = userPrompt,
            Stream = true,
            Options = new OllamaOptions { Temperature = 0.4, NumCtx = 4096 }
        };

        var json = JsonSerializer.Serialize(payload);
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/generate")
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json")
        };

        using var resp = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream);

        while (!ct.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(ct);
            if (line == null) break;
            if (line.Length == 0) continue;

            var chunk = ParseChunkOrNull(line);
            if (chunk == null) continue;

            if (!string.IsNullOrEmpty(chunk.Response))
                yield return chunk.Response;

            if (chunk.Done) yield break;
        }
    }

    private static OllamaResponse? ParseChunkOrNull(string line)
    {
        try { return JsonSerializer.Deserialize<OllamaResponse>(line); }
        catch { return null; }
    }

    // ── Internal DTOs ──

    private class OllamaRequest
    {
        [JsonPropertyName("model")] public string Model { get; set; } = "";
        [JsonPropertyName("system")] public string System { get; set; } = "";
        [JsonPropertyName("prompt")] public string Prompt { get; set; } = "";
        [JsonPropertyName("stream")] public bool Stream { get; set; }
        [JsonPropertyName("options")] public OllamaOptions Options { get; set; } = new();
    }

    private class OllamaOptions
    {
        [JsonPropertyName("temperature")] public double Temperature { get; set; } = 0.3;
        [JsonPropertyName("num_ctx")] public int NumCtx { get; set; } = 8192;
    }

    private class OllamaResponse
    {
        [JsonPropertyName("response")] public string? Response { get; set; }
        [JsonPropertyName("done")] public bool Done { get; set; }
    }
}
