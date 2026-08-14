package com.assessment.admin.security;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class TrustedRequestAuthorizerTest {

    @Test
    void rejectsMissingShortAndHistoricalDevelopmentCredentials() {
        assertFalse(new TrustedRequestAuthorizer("", "", false).isTrustedService(""));
        assertFalse(new TrustedRequestAuthorizer("short", "short", false).isAdministrator("short"));
        assertFalse(new TrustedRequestAuthorizer(
                "local-development-token", "012345678901234567890123", false)
                .isTrustedService("local-development-token"));
    }

    @Test
    void keepsServiceAndAdministratorTrustDomainsSeparate() {
        String service = "service-token-with-at-least-24-characters";
        String admin = "administrator-token-at-least-24-characters";
        TrustedRequestAuthorizer authorizer = new TrustedRequestAuthorizer(service, admin, false);

        assertTrue(authorizer.isTrustedService(service));
        assertFalse(authorizer.isTrustedService(admin));
        assertTrue(authorizer.isAdministrator(admin));
        assertFalse(authorizer.isAdministrator(service));
        assertFalse(authorizer.isAdHocSqlEnabled());
    }
}
