package com.assessment.admin.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * Central authority for machine-to-machine and administrative credentials.
 *
 * User-controlled identity headers are deliberately not considered credentials. They may
 * only describe an actor after a trusted service has authenticated with X-Service-Token.
 */
@Component
public class TrustedRequestAuthorizer {

    private static final String INSECURE_DEVELOPMENT_TOKEN = "local-development-token";

    private final String serviceToken;
    private final String adminToken;
    private final boolean adHocSqlEnabled;

    public TrustedRequestAuthorizer(
            @Value("${internal.service-token:}") String serviceToken,
            @Value("${admin.api-token:}") String adminToken,
            @Value("${admin.allow-ad-hoc-sql:false}") boolean adHocSqlEnabled) {
        this.serviceToken = normalize(serviceToken);
        this.adminToken = normalize(adminToken);
        this.adHocSqlEnabled = adHocSqlEnabled;
    }

    public boolean isTrustedService(String supplied) {
        return isStrong(serviceToken) && constantTimeEquals(serviceToken, normalize(supplied));
    }

    public boolean isAdministrator(String supplied) {
        return isStrong(adminToken) && constantTimeEquals(adminToken, normalize(supplied));
    }

    public boolean isPrivileged(String serviceCredential, String adminCredential) {
        return isTrustedService(serviceCredential) || isAdministrator(adminCredential);
    }

    public boolean isAdHocSqlEnabled() {
        return adHocSqlEnabled;
    }

    private static boolean isStrong(String token) {
        return token.length() >= 24 && !INSECURE_DEVELOPMENT_TOKEN.equals(token);
    }

    private static boolean constantTimeEquals(String expected, String supplied) {
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                supplied.getBytes(StandardCharsets.UTF_8));
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim();
    }
}
