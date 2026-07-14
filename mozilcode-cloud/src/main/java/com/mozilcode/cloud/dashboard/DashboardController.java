package com.mozilcode.cloud.dashboard;

import com.mozilcode.cloud.common.ApiResponses;
import com.mozilcode.cloud.common.CurrentUser;
import com.mozilcode.cloud.model.ModelService;
import com.mozilcode.cloud.plan.PlanService;
import com.mozilcode.cloud.plan.SubscriptionInfo;
import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DashboardController {
  private final PlanService plans;
  private final ModelService models;
  private final JdbcTemplate db;

  public DashboardController(PlanService plans, ModelService models, JdbcTemplate db) {
    this.plans = plans;
    this.models = models;
    this.db = db;
  }

  @GetMapping("/api/dashboard")
  public Map<String, Object> dashboard(HttpServletRequest request) {
    CurrentUser user = CurrentUser.from(request);
    Optional<SubscriptionInfo> subscription = plans.getActiveSubscription(user.id());

    long totalTokens = 0L;
    long totalRequests = 0L;
    try {
      Map<String, Object> totals = db.queryForMap("""
          SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                 COUNT(*) AS total_requests
          FROM usage_log WHERE user_id = ?
          """, user.id());
      totalTokens = ((Number) totals.get("total_tokens")).longValue();
      totalRequests = ((Number) totals.get("total_requests")).longValue();
    } catch (Exception ignored) {
      // empty usage is fine
    }

    Map<String, Object> out = new LinkedHashMap<>();
    out.put("user", ApiResponses.ordered(
        "user_id", user.id(),
        "email", user.email(),
        "role", user.role()
    ));
    out.put("subscription", subscription.orElse(null));
    out.put("models", models.listActiveForUsers());
    out.put("plans", plans.listPlans());
    out.put("usage_summary", ApiResponses.ordered(
        "total_tokens", totalTokens,
        "total_requests", totalRequests
    ));
    out.put("gateway", ApiResponses.ordered(
        "base_path", "/api/gateway",
        "chat_completions", "/api/gateway/chat/completions",
        "auth_header", "Authorization: Bearer <jwt>",
        "note", "Account console only. Local clients pick model and send it in request body; cloud publishes catalog + meters usage."
    ));
    return out;
  }

  @GetMapping("/api/public/info")
  public Map<String, Object> publicInfo() {
    List<?> planList = plans.listPlans();
    return ApiResponses.ordered(
        "service", "mozilcode-cloud",
        "mode", "account + plans + usage + model catalog",
        "plans", planList,
        "features", List.of(
            "JWT auth",
            "admin-managed providers",
            "admin-managed model catalog",
            "subscription redeem",
            "usage metering",
            "gateway API for local clients"
        )
    );
  }
}