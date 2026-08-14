package com.assessment.admin.controller;

import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.repository.LlmConfigRepository;
import com.assessment.admin.security.TrustedRequestAuthorizer;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/** Secret-bearing configuration endpoints for authenticated backend services only. */
@RestController
@RequestMapping("/api/admin/internal/config")
public class InternalConfigController {

    private final LlmConfigRepository llmConfigRepository;
    private final TrustedRequestAuthorizer authorizer;

    public InternalConfigController(LlmConfigRepository llmConfigRepository,
                                    TrustedRequestAuthorizer authorizer) {
        this.llmConfigRepository = llmConfigRepository;
        this.authorizer = authorizer;
    }

    @GetMapping("/llm/active")
    public ResponseEntity<Map<String, Object>> getActiveLlmConfig(
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken) {
        if (!authorizer.isTrustedService(serviceToken)) {
            return ResponseEntity.status(401)
                    .cacheControl(CacheControl.noStore())
                    .body(Map.of("success", false, "message", "服务身份校验失败"));
        }
        LlmConfig active = llmConfigRepository.findAll().stream()
                .filter(c -> Boolean.TRUE.equals(c.getIsActive()))
                .findFirst()
                .orElse(null);
        if (active == null) {
            return ResponseEntity.ok()
                    .cacheControl(CacheControl.noStore())
                    .body(Map.of("success", false, "message", "无活跃配置", "data", defaultLlmView()));
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("type", active.getType());
        data.put("apiUrl", active.getApiUrl());
        data.put("apiKey", active.getApiKey() == null ? "" : active.getApiKey());
        data.put("model", active.getModel());
        data.put("temperature", active.getTemperature() == null ? 0.7 : active.getTemperature());
        data.put("maxTokens", active.getMaxTokens() == null ? 2000 : active.getMaxTokens());
        data.put("topP", active.getTopP() == null ? 0.9 : active.getTopP());
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(Map.of("success", true, "data", data));
    }

    private Map<String, Object> defaultLlmView() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("type", "deepseek");
        data.put("apiUrl", "https://api.deepseek.com/v1");
        data.put("apiKey", "");
        data.put("model", "deepseek-chat");
        data.put("temperature", 0.7);
        data.put("maxTokens", 2000);
        data.put("topP", 0.9);
        return data;
    }
}
