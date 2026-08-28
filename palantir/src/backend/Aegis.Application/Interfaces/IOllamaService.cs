namespace Aegis.Application.Interfaces;

/// <summary>
/// Client for the Ollama LLM API.
/// Supports full-response and streaming token generation.
/// </summary>
public interface IOllamaService
{
    /// <summary>Ensure the configured model is pulled and available.</summary>
    Task EnsureModelAsync(CancellationToken ct = default);

    /// <summary>Generate a full (non-streaming) response.</summary>
    Task<string> GenerateAsync(string systemPrompt, string userPrompt, CancellationToken ct = default);

    /// <summary>Stream tokens one-by-one via async enumerable.</summary>
    IAsyncEnumerable<string> StreamAsync(string systemPrompt, string userPrompt, CancellationToken ct = default);
}
