package com.assessment.gateway;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.io.*;
import java.net.URI;
import java.util.*;

@RestController
public class GatewayController {

    private static final Logger log = LoggerFactory.getLogger(GatewayController.class);

    private final RestTemplate restTemplate = new RestTemplate();

    @GetMapping("/api/status")
    public ResponseEntity<Map<String, Object>> getStatus() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "running");
        response.put("service", "api-gateway");
        response.put("version", "1.0.0");
        response.put("services", getAvailableServices());
        return ResponseEntity.ok(response);
    }

    @RequestMapping(value = "/api/evaluation/**", method = {
        RequestMethod.GET, RequestMethod.POST, RequestMethod.PUT,
        RequestMethod.DELETE, RequestMethod.PATCH
    })
    public ResponseEntity<String> proxyEvaluation(HttpServletRequest request) {
        String path = request.getRequestURI().replaceFirst("^/api/evaluation", "");
        String query = request.getQueryString();
        String url = "http://assessment-solution-evaluation:10259" + path;
        if (query != null) {
            url += "?" + query;
        }

        HttpHeaders headers = new HttpHeaders();
        Enumeration<String> headerNames = request.getHeaderNames();
        while (headerNames.hasMoreElements()) {
            String name = headerNames.nextElement();
            if (!"host".equalsIgnoreCase(name)) {
                headers.addAll(name, Collections.list(request.getHeaders(name)));
            }
        }

        byte[] bodyBytes = new byte[0];
        try {
            InputStream inputStream = request.getInputStream();
            if (inputStream != null) {
                ByteArrayOutputStream bos = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = inputStream.read(buf)) != -1) {
                    bos.write(buf, 0, n);
                }
                bodyBytes = bos.toByteArray();
            }
        } catch (IOException ignored) {
        }

        HttpEntity<byte[]> entity = new HttpEntity<>(bodyBytes, headers);
        try {
            ResponseEntity<byte[]> response = restTemplate.exchange(
                URI.create(url),
                HttpMethod.valueOf(request.getMethod()),
                entity,
                byte[].class
            );

            HttpHeaders respHeaders = new HttpHeaders();
            respHeaders.addAll(response.getHeaders());
            respHeaders.remove(HttpHeaders.TRANSFER_ENCODING);

            return new ResponseEntity<>(response.getBody(), respHeaders, response.getStatusCode());
        } catch (Exception e) {
            log.error("Evaluation proxy failed: url={}, error={}", url, e.getMessage());
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body("{\"error\":\"方案评估服务暂不可用\",\"detail\":\"" + e.getMessage() + "\"}");
        }
    }

    private Map<String, String> getAvailableServices() {
        Map<String, String> services = new LinkedHashMap<>();
        services.put("admin-service", "http://assessment-admin:10258");
        services.put("knowledge-service", "http://assessment-knowledge:10252");
        services.put("qa-service", "http://assessment-qa:10253");
        services.put("indicator-service", "http://assessment-indicator:10254");
        services.put("evaluation-service", "http://assessment-evaluation:10255");
        services.put("ontology-service", "http://assessment-ontology:10256");
        services.put("solution-evaluation-service", "http://assessment-solution-evaluation:10259");
        return services;
    }
}
