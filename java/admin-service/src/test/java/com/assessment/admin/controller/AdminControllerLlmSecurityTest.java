package com.assessment.admin.controller;

import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.repository.LlmConfigRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminControllerLlmSecurityTest {

    private AdminController controller;
    private LlmConfigRepository repository;
    private LlmConfig active;

    @BeforeEach
    void setUp() {
        controller = new AdminController();
        repository = mock(LlmConfigRepository.class);
        ReflectionTestUtils.setField(controller, "llmConfigRepo", repository);
        ReflectionTestUtils.setField(controller, "internalServiceToken", "test-internal-token");

        active = new LlmConfig();
        active.setId("llm-test");
        active.setName("Test");
        active.setType("deepseek");
        active.setApiUrl("https://example.test/v1");
        active.setApiKey("sk-secret-value");
        active.setModel("test-model");
        active.setIsActive(true);
        when(repository.findAll()).thenReturn(List.of(active));
    }

    @Test
    void publicResponsesMaskApiKey() {
        Map<String, Object> activeBody = controller.getActiveLlmConfig().getBody();
        assertNotNull(activeBody);
        Map<?, ?> activeData = (Map<?, ?>) activeBody.get("data");
        assertEquals("********", activeData.get("apiKey"));
        assertEquals(true, activeData.get("apiKeyConfigured"));
        assertFalse(activeBody.toString().contains("sk-secret-value"));

        Map<String, Object> listBody = controller.listLlmConfigs().getBody();
        assertNotNull(listBody);
        assertFalse(listBody.toString().contains("sk-secret-value"));
    }

    @Test
    void internalResponseRequiresTokenAndReturnsSecretOnlyWhenAuthorized() {
        ResponseEntity<Map<String, Object>> denied = controller.getActiveLlmConfigInternal("wrong");
        assertEquals(HttpStatus.UNAUTHORIZED, denied.getStatusCode());
        assertFalse(String.valueOf(denied.getBody()).contains("sk-secret-value"));

        ResponseEntity<Map<String, Object>> allowed = controller.getActiveLlmConfigInternal("test-internal-token");
        assertEquals(HttpStatus.OK, allowed.getStatusCode());
        Map<?, ?> data = (Map<?, ?>) allowed.getBody().get("data");
        assertEquals("sk-secret-value", data.get("apiKey"));
    }

    @Test
    void blankOrMaskedUpdatePreservesExistingSecret() {
        when(repository.findById("llm-test")).thenReturn(Optional.of(active));

        controller.updateLlmConfig("llm-test", Map.of("apiKey", ""));
        assertEquals("sk-secret-value", active.getApiKey());

        controller.updateLlmConfig("llm-test", Map.of("apiKey", "********"));
        assertEquals("sk-secret-value", active.getApiKey());
        verify(repository, times(2)).save(active);
    }
}
