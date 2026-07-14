package com.mozilcode.cloud;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class CloudApiSmokeTest {
  @LocalServerPort
  private int port;

  private final TestRestTemplate http = new TestRestTemplate();

  @DynamicPropertySource
  static void dynamicProperties(DynamicPropertyRegistry registry) {
    registry.add("mozilcode.db.driver", () -> "org.h2.Driver");
    registry.add(
        "mozilcode.db.url",
        () -> "jdbc:h2:mem:mozilcode;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DEFAULT_NULL_ORDERING=HIGH;DB_CLOSE_DELAY=-1"
    );
    registry.add("mozilcode.db.user", () -> "sa");
    registry.add("mozilcode.db.password", () -> "");
    registry.add("mozilcode.jwt.secret", () -> "test-secret-that-is-long-enough-for-hs256");
  }

  @Test
  void userFlowAndAdminProviderManagement() {
    ResponseEntity<Map<String, Object>> health = get("/api/health", null);
    assertThat(health.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(health.getBody()).containsEntry("status", "ok");

    // Admin login (seeded)
    ResponseEntity<Map<String, Object>> adminLogin = post("/api/auth/login", Map.of(
        "email", "admin@mozilcode.local",
        "password", "admin123"
    ), null);
    assertThat(adminLogin.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(adminLogin.getBody()).containsEntry("role", "admin");
    String adminToken = (String) adminLogin.getBody().get("token");
    HttpHeaders adminAuth = authHeaders(adminToken);

    ResponseEntity<Map<String, Object>> overview = get("/api/admin/overview", adminAuth);
    assertThat(overview.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(overview.getBody()).containsKeys("providers", "models", "users");

    ResponseEntity<Map<String, Object>> providers = get("/api/admin/providers", adminAuth);
    assertThat(providers.getStatusCode()).isEqualTo(HttpStatus.OK);
    java.util.List<?> providerList = (java.util.List<?>) providers.getBody().get("providers");
    assertThat(providerList).isNotEmpty();
    Map<?, ?> firstProvider = (Map<?, ?>) providerList.getFirst();
    int providerId = ((Number) firstProvider.get("id")).intValue();

    ResponseEntity<Map<String, Object>> updateKey = put("/api/admin/providers/" + providerId, Map.of(
        "api_key", "sk-admin-test-key-123456",
        "is_active", true
    ), adminAuth);
    assertThat(updateKey.getStatusCode()).isEqualTo(HttpStatus.OK);
    Map<?, ?> updatedProvider = (Map<?, ?>) updateKey.getBody().get("provider");
    assertThat(updatedProvider.get("api_key_masked")).isNotEqualTo("sk-admin-test-key-123456");
    assertThat(updatedProvider.get("has_api_key")).isEqualTo(true);

    // Model connectivity probe returns structured result (may fail network/auth offline).
    ResponseEntity<Map<String, Object>> adminModels = get("/api/admin/models", adminAuth);
    assertThat(adminModels.getStatusCode()).isEqualTo(HttpStatus.OK);
    java.util.List<?> modelList = (java.util.List<?>) adminModels.getBody().get("models");
    assertThat(modelList).isNotEmpty();
    int modelId = ((Number) ((Map<?, ?>) modelList.getFirst()).get("id")).intValue();
    ResponseEntity<Map<String, Object>> probe = post(
        "/api/admin/models/" + modelId + "/test",
        Map.of(),
        adminAuth
    );
    assertThat(probe.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(probe.getBody()).containsKeys("ok", "model_id", "message", "latency_ms");

    // User register
    String email = "user-smoke@example.com";
    ResponseEntity<Map<String, Object>> register = post("/api/auth/register", Map.of(
        "email", email,
        "password", "secret123"
    ), null);
    assertThat(register.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    String userToken = (String) register.getBody().get("token");
    assertThat(register.getBody()).containsEntry("role", "user");
    HttpHeaders userAuth = authHeaders(userToken);

    // User cannot access admin
    ResponseEntity<Map<String, Object>> forbidden = get("/api/admin/providers", userAuth);
    assertThat(forbidden.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);

    // Legacy user BYOK endpoint is retired.
    ResponseEntity<Map<String, Object>> noKeys = get("/api/keys", userAuth);
    assertThat(noKeys.getStatusCode()).isEqualTo(HttpStatus.GONE);
    assertThat(noKeys.getBody()).containsKey("error");

    ResponseEntity<Map<String, Object>> dashboard = get("/api/dashboard", userAuth);
    assertThat(dashboard.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(dashboard.getBody()).containsKeys("models", "plans", "usage_summary");
    assertThat(dashboard.getBody()).doesNotContainKey("keys");

    ResponseEntity<Map<String, Object>> models = get("/api/models", userAuth);
    assertThat(models.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat((java.util.List<?>) models.getBody().get("models")).hasSizeGreaterThanOrEqualTo(1);
    assertThat(dashboard.getBody()).doesNotContainKey("selected_model");

    // No cloud-side default model selection.
    ResponseEntity<Map<String, Object>> noSelect = put("/api/user/model", Map.of("model_id", 1), userAuth);
    assertThat(noSelect.getStatusCode().value()).isGreaterThanOrEqualTo(400);

    ResponseEntity<Map<String, Object>> redeem = post("/api/redeem", Map.of("code", "MozilCode-FREE-500K"), userAuth);
    assertThat(redeem.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(redeem.getBody()).containsEntry("message", "兑换成功");

    ResponseEntity<Map<String, Object>> usage = get("/api/usage", userAuth);
    assertThat(usage.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(usage.getBody()).containsEntry("total_tokens", 0);
  }

  private ResponseEntity<Map<String, Object>> get(String path, HttpHeaders headers) {
    return exchange(path, HttpMethod.GET, null, headers);
  }

  private ResponseEntity<Map<String, Object>> post(String path, Object body, HttpHeaders headers) {
    return exchange(path, HttpMethod.POST, body, headers);
  }

  private ResponseEntity<Map<String, Object>> put(String path, Object body, HttpHeaders headers) {
    return exchange(path, HttpMethod.PUT, body, headers);
  }

  private ResponseEntity<Map<String, Object>> exchange(
      String path,
      HttpMethod method,
      Object body,
      HttpHeaders headers
  ) {
    HttpHeaders requestHeaders = new HttpHeaders();
    if (headers != null) {
      requestHeaders.addAll(headers);
    }
    HttpEntity<Object> entity = new HttpEntity<>(body, requestHeaders);
    return http.exchange(
        "http://127.0.0.1:" + port + path,
        method,
        entity,
        new ParameterizedTypeReference<>() {}
    );
  }

  private HttpHeaders authHeaders(String token) {
    HttpHeaders headers = new HttpHeaders();
    headers.setBearerAuth(token);
    return headers;
  }
}