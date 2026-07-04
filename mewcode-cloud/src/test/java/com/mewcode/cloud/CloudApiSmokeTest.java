package com.mewcode.cloud;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class CloudApiSmokeTest {
  @LocalServerPort
  private int port;

  private final TestRestTemplate http = new TestRestTemplate();

  @DynamicPropertySource
  static void dynamicProperties(DynamicPropertyRegistry registry) {
    registry.add("mewcode.db.driver", () -> "org.h2.Driver");
    registry.add("mewcode.db.url", () -> "jdbc:h2:mem:mewcode;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1");
    registry.add("mewcode.db.user", () -> "sa");
    registry.add("mewcode.db.password", () -> "");
    registry.add("mewcode.jwt.secret", () -> "test-secret-that-is-long-enough-for-hs256");
  }

  @Test
  void authModelRedeemAndUsageFlow() {
    ResponseEntity<Map<String, Object>> health = get("/api/health", null);
    assertThat(health.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(health.getBody()).containsEntry("status", "ok");

    String email = "smoke@example.com";
    ResponseEntity<Map<String, Object>> register = post("/api/auth/register", Map.of(
        "email", email,
        "password", "secret123"
    ), null);
    assertThat(register.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    assertThat(register.getBody()).containsEntry("message", "registered");

    ResponseEntity<Map<String, Object>> login = post("/api/auth/login", Map.of(
        "email", email,
        "password", "secret123"
    ), null);
    assertThat(login.getStatusCode()).isEqualTo(HttpStatus.OK);
    String token = (String) login.getBody().get("token");
    assertThat(token).isNotBlank();

    HttpHeaders auth = authHeaders(token);

    ResponseEntity<Map<String, Object>> models = get("/api/models", auth);
    assertThat(models.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat((java.util.List<?>) models.getBody().get("models")).hasSize(3);

    ResponseEntity<Map<String, Object>> select = put("/api/user/model", Map.of("model_id", 1), auth);
    assertThat(select.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(select.getBody()).containsEntry("message", "model selected");

    ResponseEntity<Map<String, Object>> profile = get("/api/user/profile", auth);
    assertThat(profile.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(((Number) profile.getBody().get("selected_model_id")).intValue()).isEqualTo(1);

    ResponseEntity<Map<String, Object>> beforeRedeem = get("/api/subscription", auth);
    assertThat(beforeRedeem.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(beforeRedeem.getBody().get("subscription")).isNull();

    ResponseEntity<Map<String, Object>> redeem = post("/api/redeem", Map.of("code", "MEWCODE-FREE-500K"), auth);
    assertThat(redeem.getStatusCode())
        .as("redeem response body: %s", redeem.getBody())
        .isEqualTo(HttpStatus.OK);
    assertThat(redeem.getBody()).containsEntry("message", "兑换成功");

    ResponseEntity<Map<String, Object>> duplicateRedeem = post("/api/redeem", Map.of("code", "MEWCODE-FREE-500K"), auth);
    assertThat(duplicateRedeem.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);

    ResponseEntity<Map<String, Object>> subscription = get("/api/subscription", auth);
    assertThat(subscription.getStatusCode()).isEqualTo(HttpStatus.OK);
    Map<?, ?> subscriptionBody = (Map<?, ?>) subscription.getBody().get("subscription");
    assertThat(subscriptionBody.get("plan_name")).isEqualTo("体验套餐");

    ResponseEntity<Map<String, Object>> usage = get("/api/usage", auth);
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
