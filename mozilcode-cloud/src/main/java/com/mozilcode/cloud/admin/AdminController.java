package com.mozilcode.cloud.admin;

import com.mozilcode.cloud.common.ApiResponses;
import com.mozilcode.cloud.common.CurrentUser;
import com.mozilcode.cloud.model.ModelProbeService;
import com.mozilcode.cloud.model.ModelService;
import com.mozilcode.cloud.plan.PlanService;
import com.mozilcode.cloud.provider.ProviderService;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/admin")
public class AdminController {
  private final ProviderService providers;
  private final ModelProbeService modelProbe;
  private final ModelService models;
  private final PlanService plans;
  private final JdbcTemplate db;

  public AdminController(
      ProviderService providers,
      ModelProbeService modelProbe,
      ModelService models,
      PlanService plans,
      JdbcTemplate db
  ) {
    this.providers = providers;
    this.modelProbe = modelProbe;
    this.models = models;
    this.plans = plans;
    this.db = db;
  }

  @GetMapping("/overview")
  public Map<String, Object> overview(HttpServletRequest request) {
    CurrentUser.from(request).requireAdmin();
    long users = number(db.queryForObject("SELECT COUNT(*) FROM users", Long.class));
    long modelsCount = number(db.queryForObject("SELECT COUNT(*) FROM models", Long.class));
    long providersCount = number(db.queryForObject("SELECT COUNT(*) FROM providers", Long.class));
    long activeProviders = number(db.queryForObject(
        "SELECT COUNT(*) FROM providers WHERE is_active = 1 AND api_key IS NOT NULL AND api_key <> ''",
        Long.class
    ));
    long usageRows = number(db.queryForObject("SELECT COUNT(*) FROM usage_log", Long.class));
    long totalTokens = number(db.queryForObject(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM usage_log",
        Long.class
    ));
    return ApiResponses.ordered(
        "users", users,
        "models", modelsCount,
        "providers", providersCount,
        "providers_configured", activeProviders,
        "usage_requests", usageRows,
        "usage_tokens", totalTokens,
        "plans", plans.listPlans()
    );
  }

  @GetMapping("/providers")
  public Map<String, Object> listProviders(HttpServletRequest request) {
    CurrentUser.from(request).requireAdmin();
    return Map.of("providers", providers.listAll());
  }

  @PostMapping("/providers")
  public ResponseEntity<Map<String, Object>> createProvider(
      HttpServletRequest request,
      @RequestBody ProviderBody body
  ) {
    CurrentUser.from(request).requireAdmin();
    var created = providers.create(
        body == null ? null : body.code(),
        body == null ? null : body.name(),
        body == null ? null : body.protocol(),
        body == null ? null : body.baseUrl(),
        body == null ? null : body.apiKey(),
        body == null || body.active() == null || body.active(),
        body == null || body.sortOrder() == null ? 0 : body.sortOrder()
    );
    return ResponseEntity.ok(ApiResponses.ordered("message", "provider created", "provider", created));
  }

  @PutMapping("/providers/{id}")
  public ResponseEntity<Map<String, Object>> updateProvider(
      HttpServletRequest request,
      @PathVariable int id,
      @RequestBody ProviderBody body
  ) {
    CurrentUser.from(request).requireAdmin();
    var updated = providers.update(
        id,
        body == null ? null : body.name(),
        body == null ? null : body.protocol(),
        body == null ? null : body.baseUrl(),
        body == null ? null : body.apiKey(),
        body == null ? null : body.active(),
        body == null ? null : body.sortOrder()
    );
    return ResponseEntity.ok(ApiResponses.ordered("message", "provider updated", "provider", updated));
  }

  @DeleteMapping("/providers/{id}")
  public ResponseEntity<Map<String, Object>> deleteProvider(
      HttpServletRequest request,
      @PathVariable int id
  ) {
    CurrentUser.from(request).requireAdmin();
    providers.delete(id);
    return ResponseEntity.ok(Map.of("message", "provider deleted"));
  }

  @GetMapping("/models")
  public Map<String, Object> listModels(HttpServletRequest request) {
    CurrentUser.from(request).requireAdmin();
    return Map.of("models", models.listAllForAdmin());
  }

  @PostMapping("/models")
  public ResponseEntity<Map<String, Object>> createModel(
      HttpServletRequest request,
      @RequestBody ModelBody body
  ) {
    CurrentUser.from(request).requireAdmin();
    if (body == null || body.providerId() == null) {
      return ResponseEntity.badRequest().body(ApiResponses.error("provider_id required"));
    }
    var created = models.create(
        body.name(),
        body.displayName(),
        body.providerId(),
        body.modelId(),
        body.active(),
        body.sortOrder(),
        body.thinking()
    );
    return ResponseEntity.ok(ApiResponses.ordered("message", "model created", "model", created));
  }

  @PutMapping("/models/{id}")
  public ResponseEntity<Map<String, Object>> updateModel(
      HttpServletRequest request,
      @PathVariable int id,
      @RequestBody ModelBody body
  ) {
    CurrentUser.from(request).requireAdmin();
    var updated = models.update(
        id,
        body == null ? null : body.name(),
        body == null ? null : body.displayName(),
        body == null ? null : body.providerId(),
        body == null ? null : body.modelId(),
        body == null ? null : body.active(),
        body == null ? null : body.sortOrder(),
        body == null ? null : body.thinking()
    );
    return ResponseEntity.ok(ApiResponses.ordered("message", "model updated", "model", updated));
  }

  @DeleteMapping("/models/{id}")
  public ResponseEntity<Map<String, Object>> deleteModel(
      HttpServletRequest request,
      @PathVariable int id
  ) {
    CurrentUser.from(request).requireAdmin();
    models.delete(id);
    return ResponseEntity.ok(Map.of("message", "model deleted"));
  }

  /** 测试模型是否可用：走上游 chat/completions 最小请求。 */
  @PostMapping("/models/{id}/test")
  public Map<String, Object> testModel(
      HttpServletRequest request,
      @PathVariable int id
  ) {
    CurrentUser.from(request).requireAdmin();
    return modelProbe.testModel(id);
  }

  @GetMapping("/users")
  public Map<String, Object> listUsers(HttpServletRequest request) {
    CurrentUser.from(request).requireAdmin();
    List<Map<String, Object>> users = db.query("""
        SELECT id, email, role, created_at
        FROM users ORDER BY id
        """, (rs, rowNum) -> ApiResponses.ordered(
        "id", rs.getInt("id"),
        "email", rs.getString("email"),
        "role", rs.getString("role"),
        "created_at", rs.getString("created_at")
    ));
    return Map.of("users", users);
  }

  private long number(Number value) {
    return value == null ? 0L : value.longValue();
  }

  public record ProviderBody(
      String code,
      String name,
      String protocol,
      @com.fasterxml.jackson.annotation.JsonProperty("base_url") String baseUrl,
      @com.fasterxml.jackson.annotation.JsonProperty("api_key") String apiKey,
      @com.fasterxml.jackson.annotation.JsonProperty("is_active") Boolean active,
      @com.fasterxml.jackson.annotation.JsonProperty("sort_order") Integer sortOrder
  ) {}

  public record ModelBody(
      String name,
      @com.fasterxml.jackson.annotation.JsonProperty("display_name") String displayName,
      @com.fasterxml.jackson.annotation.JsonProperty("provider_id") Integer providerId,
      @com.fasterxml.jackson.annotation.JsonProperty("model_id") String modelId,
      @com.fasterxml.jackson.annotation.JsonProperty("is_active") Boolean active,
      @com.fasterxml.jackson.annotation.JsonProperty("sort_order") Integer sortOrder,
      Boolean thinking
  ) {}
}
