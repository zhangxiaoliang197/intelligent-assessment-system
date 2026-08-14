package com.assessment.admin.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class LlmConfigSerializationTest {

    @Test
    void storedApiKeyIsWriteOnlyForJsonSerialization() throws Exception {
        LlmConfig config = new LlmConfig();
        config.setId("llm_test");
        config.setName("test");
        config.setType("openai-compatible");
        config.setApiKey("must-not-leak");

        String json = new ObjectMapper().writeValueAsString(config);
        assertFalse(json.contains("must-not-leak"));
        assertFalse(json.contains("apiKey"));

        LlmConfig deserialized = new ObjectMapper().readValue(
                "{\"apiKey\":\"accepted-on-write\"}", LlmConfig.class);
        assertTrue("accepted-on-write".equals(deserialized.getApiKey()));
    }
}
