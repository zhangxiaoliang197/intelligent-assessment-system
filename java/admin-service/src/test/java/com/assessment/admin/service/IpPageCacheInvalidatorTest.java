package com.assessment.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * ipage 缓存失效回调的行为测试：未配置跳过、成功静默、失败必须给出可见告警。
 *
 * 这条链路的关键口径是"禁止静默"——注解已落库而缓存未失效时，用户必须看到提示。
 */
class IpPageCacheInvalidatorTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private HttpServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
            server = null;
        }
    }

    private IpPageCacheInvalidator newInvalidator(String url, String token) throws Exception {
        IpPageCacheInvalidator invalidator = new IpPageCacheInvalidator();
        set(invalidator, "ipageServiceUrl", url);
        set(invalidator, "internalServiceToken", token);
        set(invalidator, "timeoutMs", 3000L);
        return invalidator;
    }

    private void set(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    @Test
    void notConfiguredShouldSkipSilently() throws Exception {
        IpPageCacheInvalidator invalidator = newInvalidator("", "");
        assertNull(invalidator.invalidate("db_1", List.of("t1")));
    }

    @Test
    void successShouldReturnNullAndSendTokenAndPayload() throws Exception {
        AtomicReference<String> tokenHeader = new AtomicReference<>();
        AtomicReference<String> body = new AtomicReference<>();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/ipage/internal/cache/invalidate", exchange -> {
            tokenHeader.set(exchange.getRequestHeaders().getFirst("X-Service-Token"));
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        server.start();

        IpPageCacheInvalidator invalidator = newInvalidator(baseUrl(), "token-1234567890");
        assertNull(invalidator.invalidate("db_1", Collections.singletonList("mock_aircraft")));

        assertEquals("token-1234567890", tokenHeader.get());
        JsonNode payload = MAPPER.readTree(body.get());
        assertEquals("db_1", payload.get("databaseId").asText());
        assertEquals("mock_aircraft", payload.get("tables").get(0).asText());
    }

    @Test
    void serverErrorShouldReturnVisibleWarning() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/ipage/internal/cache/invalidate", exchange -> {
            byte[] msg = "boom".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(500, msg.length);
            exchange.getResponseBody().write(msg);
            exchange.close();
        });
        server.start();

        IpPageCacheInvalidator invalidator = newInvalidator(baseUrl(), "");
        String warning = invalidator.invalidate("db_1", List.of("t1"));
        assertFalse(warning == null, "服务端 5xx 时必须返回告警文案");
        assertTrue(warning.contains("注解已保存"), "告警需说明注解已落库: " + warning);
        assertTrue(warning.contains("重试"), "告警需给出可执行动作: " + warning);
    }

    @Test
    void unreachableServiceShouldReturnVisibleWarning() throws Exception {
        // 指向未监听端口，模拟 ipage 容器重启中
        IpPageCacheInvalidator invalidator = newInvalidator("http://127.0.0.1:1", "");
        String warning = invalidator.invalidate("db_1", List.of("t1"));
        assertFalse(warning == null, "连接失败时必须返回告警文案");
        assertTrue(warning.contains("注解已保存"));
    }

    private String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }
}
