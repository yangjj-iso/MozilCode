package com.mozilcode.cloud.gateway;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mozilcode.cloud.common.ApiResponses;
import com.mozilcode.cloud.common.CurrentUser;
import com.mozilcode.cloud.model.ModelService;
import com.mozilcode.cloud.model.ModelService.ModelInfo;
import com.mozilcode.cloud.plan.PlanService;
import com.mozilcode.cloud.plan.SubscriptionInfo;
import com.mozilcode.cloud.provider.ProviderService;
import jakarta.servlet.http.HttpServletRequest;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
public class GatewayController {
  private static final TypeReference<Map<String, Object>> STRING_OBJECT_MAP = new TypeReference<>() {};

  private final ModelService models;
  private final PlanService plans;
  private final ProviderService providers;
  private final RateLimiter rateLimiter;
  private final JdbcTemplate db;
  private final ObjectMapper objectMapper;
  private final HttpClient httpClient = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(30))
      .build();

  public GatewayController(
      ModelService models,
      PlanService plans,
      ProviderService providers,
      RateLimiter rateLimiter,
      JdbcTemplate db,
      ObjectMapper objectMapper
  ) {
    this.models = models;
    this.plans = plans;
    this.providers = providers;
    this.rateLimiter = rateLimiter;
    this.db = db;
    this.objectMapper = objectMapper;
  }

  @RequestMapping("/api/gateway/**")
  public ResponseEntity<StreamingResponseBody> proxy(HttpServletRequest request) throws IOException, InterruptedException {
    CurrentUser user = CurrentUser.from(request);
    RateLimiter.Result rate = rateLimiter.check(user.id());
    if (!rate.allowed()) {
      return json(HttpStatus.TOO_MANY_REQUESTS, ApiResponses.ordered(
          "error", "rate limit exceeded",
          "retry_at", rate.resetAt().toString(),
          "limit", rate.limit(),
          "window", rate.window().toString()
      ));
    }

    Optional<SubscriptionInfo> subscription = plans.getActiveSubscription(user.id());
    if (subscription.isEmpty()) {
      return json(HttpStatus.PAYMENT_REQUIRED, ApiResponses.error(
          "no active subscription. Redeem a code at POST /api/redeem"
      ));
    }
    SubscriptionInfo sub = subscription.get();
    if (sub.tokenUsed() >= sub.tokenQuota()) {
      return json(HttpStatus.PAYMENT_REQUIRED, ApiResponses.ordered(
          "error", "token quota exhausted",
          "token_used", sub.tokenUsed(),
          "token_quota", sub.tokenQuota()
      ));
    }

    byte[] rawBody = request.getInputStream().readAllBytes();
    String requestedModel = extractRequestedModel(rawBody);
    if (requestedModel == null || requestedModel.isBlank()) {
      return json(HttpStatus.BAD_REQUEST, ApiResponses.error(
          "model required in request body. GET /api/models for catalog, then send body.model"
      ));
    }
    Optional<ModelInfo> resolved = models.resolveActive(requestedModel);
    if (resolved.isEmpty()) {
      return json(HttpStatus.BAD_REQUEST, ApiResponses.error(
          "model not available: " + requestedModel + ". GET /api/models for catalog"
      ));
    }
    ModelInfo model = resolved.get();

    // Resolve runtime base_url + api_key from admin-managed provider.
    String baseUrl = model.baseUrl();
    String apiKey = null;
    if (model.providerId() != null) {
      var provider = providers.getRaw(model.providerId());
      if (provider.isEmpty() || !provider.get().active()) {
        return json(HttpStatus.SERVICE_UNAVAILABLE, ApiResponses.error(
            "provider unavailable for model=" + model.name()
        ));
      }
      baseUrl = provider.get().baseUrl();
      apiKey = provider.get().apiKey();
    } else {
      var provider = providers.getRawByCode(model.provider());
      if (provider.isPresent() && provider.get().active()) {
        baseUrl = provider.get().baseUrl();
        apiKey = provider.get().apiKey();
      }
    }
    if (apiKey == null || apiKey.isBlank()) {
      return json(HttpStatus.SERVICE_UNAVAILABLE, ApiResponses.error(
          "provider api key not configured by admin for provider=" + model.provider()
      ));
    }

    // Normalize to upstream model_id; client may have sent catalog name.
    byte[] body = overrideModel(rawBody, model.modelId());
    String upstreamUrl = upstreamUrl(request, baseUrl);
    Instant start = Instant.now();

    HttpRequest upstreamRequest = HttpRequest.newBuilder(URI.create(upstreamUrl))
        .timeout(Duration.ofMinutes(5))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer " + apiKey)
        .POST(HttpRequest.BodyPublishers.ofByteArray(body))
        .build();

    HttpResponse<java.io.InputStream> upstream;
    try {
      upstream = httpClient.send(upstreamRequest, HttpResponse.BodyHandlers.ofInputStream());
    } catch (Exception e) {
      return json(HttpStatus.BAD_GATEWAY, ApiResponses.ordered(
          "error", "upstream failed: " + e.getMessage(),
          "detail", "model=" + model.name() + " url=" + upstreamUrl
      ));
    }

    if (upstream.statusCode() >= 400) {
      String detail = new String(upstream.body().readAllBytes(), StandardCharsets.UTF_8);
      return json(upstream.statusCode(), ApiResponses.ordered(
          "error", "provider error",
          "detail", detail
      ));
    }

    String contentType = upstream.headers()
        .firstValue("Content-Type")
        .orElse("");
    boolean stream = contentType.contains("text/event-stream")
        || new String(body, StandardCharsets.UTF_8).contains("\"stream\":true");

    if (stream) {
      StreamingResponseBody streamBody = output -> proxySse(upstream, output, user.id(), model, start);
      return ResponseEntity.ok()
          .header("X-RateLimit-Limit", Integer.toString(rate.limit()))
          .header("X-RateLimit-Remaining", Integer.toString(rate.remaining()))
          .header(HttpHeaders.CACHE_CONTROL, "no-cache")
          .header(HttpHeaders.CONNECTION, "keep-alive")
          .contentType(MediaType.TEXT_EVENT_STREAM)
          .body(streamBody);
    }

    byte[] responseBody = upstream.body().readAllBytes();
    Usage usage = extractUsage(responseBody);
    recordUsage(user.id(), model, usage.inputTokens(), usage.outputTokens(), start);
    return ResponseEntity.ok()
        .header("X-RateLimit-Limit", Integer.toString(rate.limit()))
        .header("X-RateLimit-Remaining", Integer.toString(rate.remaining()))
        .contentType(MediaType.APPLICATION_JSON)
        .body(output -> output.write(responseBody));
  }

  private ResponseEntity<StreamingResponseBody> json(int status, Object payload) {
    return ResponseEntity.status(status)
        .contentType(MediaType.APPLICATION_JSON)
        .body(output -> objectMapper.writeValue(output, payload));
  }

  private ResponseEntity<StreamingResponseBody> json(HttpStatus status, Object payload) {
    return json(status.value(), payload);
  }

  private String extractRequestedModel(byte[] rawBody) {
    try {
      Map<String, Object> payload = objectMapper.readValue(rawBody, STRING_OBJECT_MAP);
      Object model = payload.get("model");
      return model == null ? null : String.valueOf(model);
    } catch (Exception ignored) {
      return null;
    }
  }

  private byte[] overrideModel(byte[] rawBody, String modelId) {
    try {
      Map<String, Object> payload = objectMapper.readValue(rawBody, STRING_OBJECT_MAP);
      payload.put("model", modelId);
      return objectMapper.writeValueAsBytes(payload);
    } catch (Exception ignored) {
      return rawBody;
    }
  }

  private String upstreamUrl(HttpServletRequest request, String baseUrl) {
    String prefix = "/api/gateway";
    String uri = request.getRequestURI();
    String path = uri.startsWith(prefix) ? uri.substring(prefix.length()) : "";
    if (path.isBlank() || "/".equals(path)) {
      path = "chat/completions";
    }
    return trimRight(baseUrl, "/") + "/" + trimLeft(path, "/");
  }

  private void proxySse(
      HttpResponse<java.io.InputStream> upstream,
      java.io.OutputStream output,
      int userId,
      ModelInfo model,
      Instant start
  ) throws IOException {
    int totalInput = 0;
    int totalOutput = 0;

    try (BufferedReader reader = new BufferedReader(new InputStreamReader(upstream.body(), StandardCharsets.UTF_8))) {
      String line;
      while ((line = reader.readLine()) != null) {
        output.write(line.getBytes(StandardCharsets.UTF_8));
        output.write('\n');
        output.flush();

        if (line.startsWith("data: ")) {
          String data = line.substring("data: ".length());
          if (!"[DONE]".equals(data)) {
            Usage usage = extractUsage(data.getBytes(StandardCharsets.UTF_8));
            if (usage.inputTokens() > 0 || usage.outputTokens() > 0) {
              totalInput = usage.inputTokens();
              totalOutput = usage.outputTokens();
            }
          }
        }
      }
    } finally {
      recordUsage(userId, model, totalInput, totalOutput, start);
    }
  }

  private Usage extractUsage(byte[] body) {
    try {
      Map<String, Object> payload = objectMapper.readValue(body, STRING_OBJECT_MAP);
      Object rawUsage = payload.get("usage");
      if (!(rawUsage instanceof Map<?, ?> usage)) {
        return new Usage(0, 0);
      }
      return new Usage(
          intValue(usage.get("prompt_tokens")),
          intValue(usage.get("completion_tokens"))
      );
    } catch (Exception ignored) {
      return new Usage(0, 0);
    }
  }

  private void recordUsage(int userId, ModelInfo model, int inputTokens, int outputTokens, Instant start) {
    long latencyMs = Duration.between(start, Instant.now()).toMillis();
    db.update("""
        INSERT INTO usage_log (user_id, model, input_tokens, output_tokens, latency_ms)
        VALUES (?, ?, ?, ?, ?)
        """, userId, model.name(), inputTokens, outputTokens, latencyMs);

    if (inputTokens > 0 || outputTokens > 0) {
      plans.addUsage(userId, inputTokens, outputTokens);
    }
  }

  private int intValue(Object value) {
    return value instanceof Number number ? number.intValue() : 0;
  }

  private static String trimLeft(String value, String token) {
    String out = value;
    while (out.startsWith(token)) {
      out = out.substring(token.length());
    }
    return out;
  }

  private static String trimRight(String value, String token) {
    String out = value;
    while (out.endsWith(token)) {
      out = out.substring(0, out.length() - token.length());
    }
    return out;
  }

  private record Usage(int inputTokens, int outputTokens) {}
}
