package com.assessment.admin.service;

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

/**
 * 注解变更后回调 interactive-page-service（ipage）失效其进程内缓存。
 *
 * 背景：ipage 的维度图/档案索引缓存以数据源标识为键且无失效入口，
 * 注解改完不重启 ipage 就看不到效果（用户会误以为是自己注解写错了）。
 *
 * 约定：
 * 1. 未配置 {@code ipage.service-url} 时视为"本地开发无 ipage"，直接返回 null（不告警）；
 * 2. 已配置但调用失败时返回中文告警文案，由调用方写进响应 warnings ——
 *    注解已落库但缓存未失效，必须让用户看见，禁止静默；
 * 3. 不重试：失败信息即提示，用户重试保存即可再触发一次。
 */
@Service
public class IpPageCacheInvalidator {

    private static final Logger logger = LoggerFactory.getLogger(IpPageCacheInvalidator.class);

    private static final String INVALIDATE_PATH = "/ipage/internal/cache/invalidate";

    @Value("${ipage.service-url:}")
    private String ipageServiceUrl;

    @Value("${internal.service-token:}")
    private String internalServiceToken;

    @Value("${ipage.invalidate-timeout-ms:5000}")
    private long timeoutMs;

    private final ObjectMapper mapper = new ObjectMapper();

    /**
     * 通知 ipage 失效指定数据源/表的缓存。
     *
     * @param databaseId 数据源标识（为空表示全量失效，由 ipage 侧决定）
     * @param tableNames 发生变更的表名列表（为空表示该数据源全量失效）
     * @return null 表示成功或未配置；非空为中文告警文案
     */
    public String invalidate(String databaseId, List<String> tableNames) {
        if (ipageServiceUrl == null || ipageServiceUrl.isBlank()) {
            logger.debug("未配置 ipage.service-url，跳过缓存失效回调");
            return null;
        }
        try {
            List<String> tables = new ArrayList<>();
            if (tableNames != null) {
                for (String t : tableNames) {
                    if (t != null && !t.isBlank() && !tables.contains(t)) {
                        tables.add(t);
                    }
                }
            }
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("databaseId", databaseId == null ? "" : databaseId);
            payload.put("tables", tables);

            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(trimTrailingSlash(ipageServiceUrl) + INVALIDATE_PATH))
                    .timeout(Duration.ofMillis(Math.max(500, timeoutMs)))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            mapper.writeValueAsString(payload)));
            if (internalServiceToken != null && !internalServiceToken.isBlank()) {
                builder.header("X-Service-Token", internalServiceToken);
            }

            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofMillis(Math.max(500, timeoutMs)))
                    .build();
            HttpResponse<String> resp = client.send(builder.build(),
                    HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() / 100 != 2) {
                String msg = "注解已保存，但通知页面服务失效缓存失败（HTTP " + resp.statusCode()
                        + "），页面可能仍使用旧注解，请重试保存";
                logger.warn("ipage 缓存失效回调失败: status={} body={}", resp.statusCode(),
                        abbreviate(resp.body()));
                return msg;
            }
            logger.info("ipage 缓存失效回调成功: databaseId={} tables={}", databaseId, tables);
            return null;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            String msg = "注解已保存，但通知页面服务失效缓存被中断，页面可能仍使用旧注解，请重试保存";
            logger.warn(msg, e);
            return msg;
        } catch (Exception e) {
            String msg = "注解已保存，但通知页面服务失效缓存失败（" + e.getClass().getSimpleName()
                    + "），页面可能仍使用旧注解，请重试保存";
            logger.warn(msg, e);
            return msg;
        }
    }

    private String trimTrailingSlash(String url) {
        String u = url.trim();
        while (u.endsWith("/")) {
            u = u.substring(0, u.length() - 1);
        }
        return u;
    }

    private String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        return text.length() <= 200 ? text : text.substring(0, 200) + "…";
    }
}
