package com.mozilcode.cloud.plan;

import com.mozilcode.cloud.common.ApiResponses;
import com.mozilcode.cloud.common.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class PlanController {
  private final PlanService plans;

  public PlanController(PlanService plans) {
    this.plans = plans;
  }

  @GetMapping("/api/plans")
  public Map<String, Object> listPlans() {
    return Map.of("plans", plans.listPlans());
  }

  @PostMapping("/api/redeem")
  public ResponseEntity<Map<String, Object>> redeem(
      HttpServletRequest request,
      @RequestBody RedeemRequest body
  ) {
    CurrentUser user = CurrentUser.from(request);
    if (body == null || body.code() == null || body.code().isBlank()) {
      return ResponseEntity.badRequest().body(ApiResponses.error("code required"));
    }

    try {
      PlanService.RedeemResult result = plans.redeem(user.id(), body.code());
      return ResponseEntity.ok(ApiResponses.ordered(
          "message", "兑换成功",
          "subscription", ApiResponses.ordered(
              "id", result.id(),
              "plan_name", result.planName(),
              "token_quota", result.tokenQuota(),
              "expires_at", result.expiresAt()
          )
      ));
    } catch (PlanService.RedeemException e) {
      return ResponseEntity.status(e.status()).body(ApiResponses.error(e.getMessage()));
    } catch (Exception e) {
      return ResponseEntity.internalServerError().body(ApiResponses.error(e.getMessage()));
    }
  }

  @GetMapping("/api/subscription")
  public Map<String, Object> getSubscription(HttpServletRequest request) {
    CurrentUser user = CurrentUser.from(request);
    return plans.getActiveSubscription(user.id())
        .<Map<String, Object>>map(subscription -> Map.of("subscription", subscription))
        .orElseGet(() -> ApiResponses.ordered(
            "subscription", null,
            "message", "no active subscription"
        ));
  }

  public record RedeemRequest(String code) {}
}
