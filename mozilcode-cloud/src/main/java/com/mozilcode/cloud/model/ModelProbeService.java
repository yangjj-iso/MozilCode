package com.mozilcode.cloud.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mozilcode.cloud.model.ModelService.ModelInfo;
import com.mozilcode.cloud.provider.ProviderService;
import com.mozilcode.cloud.provider.ProviderService.ProviderRaw;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * 管理员侧模型探测：用目录模型对应的提供商密钥，发一次最小 chat/completions。
 * 不落库、不扣用户配额。
 */
@Service
public class ModelProbeService {
  private static final Duration TIMEOUT = Duration.ofSeconds(20);

  private final ModelService models;
  private final ProviderService providers;
  private final ObjectMapper objectMapper;
  private final HttpClient httpClient = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(8))
      .build();

  public ModelProbeService(ModelService models, ProviderService providers, ObjectMapper objectMapper) {
    this.models = models;
    this.providers = providers;
    this.objectMapper = objectMapper;
  }

  public Map<String, Object> testModel(int modelId) {
    ModelInfo model = models.getByIdAny(modelId)
        .orElseThrow(() -> new ModelService.ModelException(404, "model not found"));

    ProviderRaw provider = resolveProvider(model);
    if (provider == null) {
      return fail(model, null, null, 0, "provider missing", "模型未绑定有效提供商");
    }
    String baseUrl = provider.baseUrl() == null ? "" : provider.baseUrl().trim();
    String apiKey = provider.apiKey() == null ? "" : provider.apiKey().trim();
    if (baseUrl.isBlank()) {
      return fail(model, provider, null, 0, "base_url empty", null);
    }
    if (apiKey.isBlank()) {
      return fail(model, provider, null, 0, "api_key empty", null);
    }

    String probeUrl = chatCompletionsUrl(baseUrl);
    Instant start = Instant.now();
    try {
      byte[] body = objectMapper.writeValueAsBytes(Map.of(
          "model", model.modelId(),
          "messages", List.of(Map.of(
              "role", "user",
              "content", "ping"
          )),
          "max_tokens", 1,
          "stream", false
      ));
      HttpRequest request = HttpRequest.newBuilder(URI.create(probeUrl))
          .timeout(TIMEOUT)
          .header("Authorization", "Bearer " + apiKey)
          .header("Content-Type", "application/json")
          .header("Accept", "application/json")
          .POST(HttpRequest.BodyPublishers.ofByteArray(body))
          .build();
      HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
      long latencyMs = Duration.between(start, Instant.now()).toMillis();
      int status = response.statusCode();
      String raw = response.body() == null ? "" : response.body();
      String snippet = snippet(raw, 240);

      if (status >= 200 && status < 300) {
        return ok(model, provider, probeUrl, status, latencyMs, snippet);
      }
      if (status == 401 || status == 403) {
        return fail(model, provider, probeUrl, latencyMs, "auth failed", status + " " + snippet);
      }
      if (status == 404) {
        return fail(model, provider, probeUrl, latencyMs, "model not found upstream", status + " " + snippet);
      }
      return fail(model, provider, probeUrl, latencyMs, "upstream error", status + " " + snippet);
    } catch (IllegalArgumentException e) {
      return fail(model, provider, probeUrl, 0, "invalid base_url", e.getMessage());
    } catch (Exception e) {
      long latencyMs = Duration.between(start, Instant.now()).toMillis();
      String message = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
      return fail(model, provider, probeUrl, latencyMs, "network error", message);
    }
  }

  private ProviderRaw resolveProvider(ModelInfo model) {
    if (model.providerId() != null) {
      return providers.getRaw(model.providerId()).orElse(null);
    }
    if (model.provider() != null && !model.provider().isBlank()) {
      return providers.getRawByCode(model.provider()).orElse(null);
    }
    return null;
  }

  private Map<String, Object> ok(
      ModelInfo model,
      ProviderRaw provider,
      String probeUrl,
      int status,
      long latencyMs,
      String detail
  ) {
    Map<String, Object> out = base(model, provider, probeUrl, latencyMs);
    out.put("ok", true);
    out.put("status", status);
    out.put("message", "connected");
    out.put("detail", detail);
    return out;
  }

  private Map<String, Object> fail(
      ModelInfo model,
      ProviderRaw provider,
      String probeUrl,
      long latencyMs,
      String message,
      String detail
  ) {
    Map<String, Object> out = base(model, provider, probeUrl, latencyMs);
    out.put("ok", false);
    out.put("status", 0);
    out.put("message", message);
    out.put("detail", detail == null ? "" : detail);
    return out;
  }

  private Map<String, Object> base(
      ModelInfo model,
      ProviderRaw provider,
      String probeUrl,
      long latencyMs
  ) {
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("model_id", model.id());
    out.put("model", model.name());
    out.put("display_name", model.displayName());
    out.put("upstream_model_id", model.modelId());
    if (provider != null) {
      out.put("provider_id", provider.id());
      out.put("provider", provider.code());
      out.put("provider_name", provider.name());
      out.put("base_url", provider.baseUrl());
    }
    out.put("probe_url", probeUrl);
    out.put("latency_ms", latencyMs);
    return out;
  }

  /** 将 OpenAI 兼容 base 规范化成 chat/completions 地址。 */
  static String chatCompletionsUrl(String baseUrl) {
    String base = trimRight(baseUrl.trim(), "/");
    if (base.endsWith("/chat/completions")) {
      return base;
    }
    if (base.endsWith("/v1")
        || base.endsWith("/compatible-mode/v1")
        || base.endsWith("/step_plan/v1")
        || base.matches(".*/v\\d+$")) {
      return base + "/chat/completions";
    }
    if (!base.contains("/v1/")) {
      return base + "/v1/chat/completions";
    }
    return base + "/chat/completions";
  }

  private static String trimRight(String value, String token) {
    String out = value;
    while (out.endsWith(token)) {
      out = out.substring(0, out.length() - token.length());
    }
    return out;
  }

  private static String snippet(String text, int max) {
    String value = text == null ? "" : text.replaceAll("\\s+", " ").trim();
    if (value.length() <= max) {
      return value;
    }
    return value.substring(0, max) + "…";
  }
}