package com.assessment.gateway;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class GatewayController {

    @GetMapping("/status")
    public ResponseEntity<Map<String, Object>> getStatus() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "running");
        response.put("service", "api-gateway");
        response.put("version", "1.0.0");
        response.put("services", getAvailableServices());
        return ResponseEntity.ok(response);
    }

    private Map<String, String> getAvailableServices() {
        Map<String, String> services = new HashMap<>();
        services.put("admin-service", "http://localhost:8081");
        services.put("knowledge-service", "http://localhost:8001");
        services.put("qa-service", "http://localhost:8002");
        services.put("indicator-service", "http://localhost:8003");
        services.put("evaluation-service", "http://localhost:8004");
        services.put("ontology-service", "http://localhost:8005");
        return services;
    }
}
