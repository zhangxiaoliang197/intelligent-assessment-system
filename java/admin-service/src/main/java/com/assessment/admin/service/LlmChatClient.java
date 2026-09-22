package com.assessment.admin.service;

import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.repository.LlmConfigRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 大模型 chat 调用封装（OpenAI 兼容协议）。
 *
 * 设计要点：
 * 1. 只依赖 {@code ass_llm_config} 里已配置的模型（active 优先），不引入任何新依赖；
 * 2. 最低温度（默认 0.1）+ 受限 max_tokens：本类只服务"结构化抽取"这类确定性任务；
 * 3. JSON 模式：优先带 {@code response_format=json_object}，服务端不认时自动去掉重试一次；
 * 4. 失败一律抛出带中文说明的异常，由调用方决定降级（绝不返回半截内容冒充成功）。
 */
@Service
public class LlmChatClient {

    private static final Logger logger = LoggerFactory.getLogger(LlmChatClient.class);

    private final LlmConfigRepository llmConfigRepo;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${annotation.draft.timeout-ms:90000}")
    private long timeoutMs = 90000;

    @Value("${annotation.draft.max-tokens:6000}")
    private int maxTokens = 6000;

    @Value("${annotation.draft.temperature:0.1}")
    private double temperature = 0.1;

    public LlmChatClient(LlmConfigRepository llmConfigRepo) {
        this.llmConfigRepo = llmConfigRepo;
    }

    /**
     * 规范化 OpenAI 兼容的 chat/completions 地址（与配置页"测试连接"同一口径）。
     *
     * @param apiUrl 形如 {@code https://api.deepseek.com/v1} 或已含完整路径的地址
     * @return 可直连的 chat/completions 地址；入参为空时返回空串
     */
    public static String normalizeChatUrl(String apiUrl) {
        String url = apiUrl == null ? "" : apiUrl.trim().replaceAll("/+$", "");
        if (url.isEmpty()) {
            return "";
        }
        if (!url.endsWith("/chat/completions")) {
            if (!url.endsWith("/v1")) {
                url += "/v1";
            }
            url += "/chat/completions";
        }
        return url;
    }

    /** 取当前生效的大模型配置：active 优先，其次第一条；无配置返回 empty。 */
    public Optional<LlmConfig> activeConfig() {
        List<LlmConfig> all = llmConfigRepo.findAll();
        if (all.isEmpty()) {
            return Optional.empty();
        }
        return all.stream().filter(c -> Boolean.TRUE.equals(c.getIsActive())).findFirst()
                .or(() -> Optional.of(all.get(0)));
    }

    /**
     * 单次对话调用。
     *
     * @param config       大模型配置（须含 apiUrl / apiKey / model）
     * @param systemPrompt 系统提示词
     * @param userPrompt   用户提示词
     * @param jsonMode     是否要求返回 JSON 对象
     * @return 模型返回的正文（content）
     * @throws IllegalStateException 配置缺失、网络失败或返回体不可解析时
     */
    public String chat(LlmConfig config, String systemPrompt, String userPrompt, boolean jsonMode) {
        if (config == null) {
            throw new IllegalStateException("未找到可用的大模型配置，请先在「大模型配置」中设置并启用");
        }
        String url = normalizeChatUrl(config.getApiUrl());
        if (url.isEmpty()) {
            throw new IllegalStateException("大模型配置缺少 API 地址");
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", config.getModel() == null || config.getModel().isBlank()
                ? "deepseek-chat" : config.getModel());
        List<Map<String, String>> messages = new ArrayList<>();
        messages.add(Map.of("role", "system", "content", systemPrompt));
        messages.add(Map.of("role", "user", "content", userPrompt));
        body.put("messages", messages);
        body.put("temperature", temperature);
        body.put("max_tokens", maxTokens);
        body.put("stream", false);
        if (jsonMode) {
            body.put("response_format", Map.of("type", "json_object"));
        }

        try {
            return request(config, url, body);
        } catch (IllegalStateException e) {
            // 部分自建/代理网关不认 response_format：去掉后重试一次
            if (jsonMode && String.valueOf(e.getMessage()).contains("response_format")) {
                logger.warn("服务端不支持 response_format，去掉后重试一次: {}", e.getMessage());
                body.remove("response_format");
                return request(config, url, body);
            }
            throw e;
        }
    }

    private String request(LlmConfig config, String url, Map<String, Object> body) {
        long started = System.currentTimeMillis();
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + (config.getApiKey() == null ? "" : config.getApiKey()))
                    .POST(HttpRequest.BodyPublishers.ofString(
                            mapper.writeValueAsString(body)))
                    .timeout(Duration.ofMillis(Math.max(5000, timeoutMs)))
                    .build();

            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofMillis(Math.max(5000, timeoutMs)))
                    .build();
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            long elapsed = System.currentTimeMillis() - started;

            if (response.statusCode() / 100 != 2) {
                String detail = abbreviate(response.body());
                logger.warn("大模型调用失败: status={} body={}", response.statusCode(), detail);
                throw new IllegalStateException("大模型调用失败（HTTP " + response.statusCode()
                        + "）：" + detail);
            }
            JsonNode root = mapper.readTree(response.body());
            JsonNode content = root.path("choices").path(0).path("message").path("content");
            if (content.isMissingNode() || content.isNull() || content.asText().isBlank()) {
                throw new IllegalStateException("大模型返回内容为空，请检查模型名称与配额");
            }
            logger.info("大模型调用完成：model={} 耗时={}ms 输出长度={}",
                    body.get("model"), elapsed, content.asText().length());
            return content.asText();
        } catch (IllegalStateException e) {
            throw e;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("大模型调用被中断");
        } catch (Exception e) {
            logger.warn("大模型调用异常: {}", e.getMessage());
            throw new IllegalStateException("大模型调用异常：" + e.getClass().getSimpleName()
                    + " - " + abbreviate(e.getMessage()));
        }
    }

    private static String abbreviate(String text) {
        String value = text == null ? "" : text.trim();
        return value.length() <= 300 ? value : value.substring(0, 300) + "…";
    }
}
