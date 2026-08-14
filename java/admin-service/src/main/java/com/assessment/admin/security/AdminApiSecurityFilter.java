package com.assessment.admin.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Deny-by-default perimeter for admin-service HTTP APIs. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class AdminApiSecurityFilter extends OncePerRequestFilter {

    private final TrustedRequestAuthorizer authorizer;
    private final ObjectMapper objectMapper;

    public AdminApiSecurityFilter(TrustedRequestAuthorizer authorizer, ObjectMapper objectMapper) {
        this.authorizer = authorizer;
        this.objectMapper = objectMapper;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (!path.startsWith("/api/admin") && !path.startsWith("/api/dataquery")) return true;
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) return true;
        if (path.equals("/api/admin/health") || path.equals("/api/admin/info")) return true;
        if ("GET".equalsIgnoreCase(request.getMethod())
                && path.startsWith("/api/admin/situation/share/")) return true;
        if ("GET".equalsIgnoreCase(request.getMethod())
                && path.equals("/api/admin/config/map/active")) return true;
        // Compatibility views are intentionally public but never include an API key.
        return "GET".equalsIgnoreCase(request.getMethod())
                && (path.equals("/api/admin/config/llm/active")
                || path.equals("/api/admin/config/llm/list"));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String serviceToken = request.getHeader("X-Service-Token");
        String adminToken = request.getHeader("X-Admin-Token");
        boolean serviceOnly = requiresTrustedServiceOnly(request);
        boolean serviceOrAdmin = allowsTrustedRuntimeService(request);
        boolean permitted = serviceOnly
                ? authorizer.isTrustedService(serviceToken)
                : serviceOrAdmin
                    ? authorizer.isTrustedService(serviceToken) || authorizer.isAdministrator(adminToken)
                    : authorizer.isAdministrator(adminToken);
        if (permitted) {
            filterChain.doFilter(request, response);
            return;
        }
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setHeader("Cache-Control", "no-store");
        objectMapper.writeValue(response.getWriter(), Map.of(
                "success", false,
                "message", serviceOnly ? "缺少有效的服务身份" : "缺少有效的管理凭据"));
    }

    private boolean requiresTrustedServiceOnly(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.startsWith("/api/admin/internal/")) return true;
        if (path.startsWith("/api/admin/situation/")) return true;
        if (path.equals("/api/admin/dataset/authorized-list")) return true;
        if (path.equals("/api/admin/export/for-llm")) return true;
        return path.matches("/api/admin/dataset/[^/]+/query");
    }

    /**
     * Exact runtime API allow-list. GET entries expose metadata required for SQL planning;
     * the sole POST entry is still constrained to one validated read-only SQL statement by
     * SqlExecutionService. All management mutations remain administrator-only.
     */
    private boolean allowsTrustedRuntimeService(HttpServletRequest request) {
        String method = request.getMethod();
        String path = request.getRequestURI();
        // 聊天会话数据由 qa/indicator/evaluation 等可信运行时服务通过 X-Service-Token 读写，
        // 管理面则通过 X-Admin-Token 访问，二者均属可信调用，不应被默认拒绝。
        if (path.startsWith("/api/admin/chat/")) return true;
        if ("GET".equalsIgnoreCase(method)) {
            return path.equals("/api/admin/database/list")
                    || path.matches("/api/admin/database/[^/]+/tables")
                    || path.matches("/api/admin/database/[^/]+/table-structure")
                    || path.equals("/api/admin/dataset/list")
                    || path.matches("/api/admin/dataset/[^/]+")
                    || path.matches("/api/admin/dataset/[^/]+/structure")
                    || path.matches("/api/admin/dataset/[^/]+/data")
                    || path.equals("/api/admin/indicator/list")
                    || path.matches("/api/admin/indicator/[^/]+")
                    || path.matches("/api/admin/indicator/[^/]+/linkage");
        }
        return "POST".equalsIgnoreCase(method)
                && (path.matches("/api/admin/database/[^/]+/execute-sql")
                    || path.matches("/api/admin/dataset/[^/]+/execute-query"));
    }
}
