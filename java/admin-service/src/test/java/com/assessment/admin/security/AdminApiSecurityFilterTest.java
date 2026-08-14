package com.assessment.admin.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;

class AdminApiSecurityFilterTest {

    private static final String SERVICE = "service-token-with-at-least-24-characters";
    private static final String ADMIN = "administrator-token-at-least-24-characters";

    private AdminApiSecurityFilter filter;

    @BeforeEach
    void setUp() {
        filter = new AdminApiSecurityFilter(
                new TrustedRequestAuthorizer(SERVICE, ADMIN, false), new ObjectMapper());
    }

    @Test
    void trustedServiceCanReadOnlyRuntimeMetadataAndExecuteQaQuery() throws Exception {
        assertStatus("GET", "/api/admin/database/list", "X-Service-Token", SERVICE, 204);
        assertStatus("GET", "/api/admin/database/db_1/tables", "X-Service-Token", SERVICE, 204);
        assertStatus("GET", "/api/admin/database/db_1/table-structure", "X-Service-Token", SERVICE, 204);
        assertStatus("GET", "/api/admin/dataset/list", "X-Service-Token", SERVICE, 204);
        assertStatus("GET", "/api/admin/indicator/ind_1/linkage", "X-Service-Token", SERVICE, 204);
        assertStatus("POST", "/api/admin/database/db_1/execute-sql", "X-Service-Token", SERVICE, 204);
    }

    @Test
    void trustedServiceCannotMutateManagementState() throws Exception {
        assertStatus("POST", "/api/admin/database", "X-Service-Token", SERVICE, 401);
        assertStatus("PUT", "/api/admin/dataset/ds_1", "X-Service-Token", SERVICE, 401);
        assertStatus("DELETE", "/api/admin/indicator/ind_1", "X-Service-Token", SERVICE, 401);
        assertStatus("POST", "/api/admin/config/llm", "X-Service-Token", SERVICE, 401);
    }

    @Test
    void administratorCanUseManagementAndRuntimeMetadataButNotServiceOnlySecrets() throws Exception {
        assertStatus("POST", "/api/admin/database", "X-Admin-Token", ADMIN, 204);
        assertStatus("GET", "/api/admin/database/list", "X-Admin-Token", ADMIN, 204);
        assertStatus("GET", "/api/admin/internal/config/llm/active", "X-Admin-Token", ADMIN, 401);
    }

    private void assertStatus(String method, String path, String header, String credential,
                              int expectedStatus) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(method, path);
        request.addHeader(header, credential);
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = (req, res) -> ((MockHttpServletResponse) res).setStatus(204);
        filter.doFilter(request, response, chain);
        assertEquals(expectedStatus, response.getStatus(), method + " " + path);
    }
}
