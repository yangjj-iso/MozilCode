package com.mozilcode.cloud;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {
  @GetMapping("/api/health")
  public Map<String, Object> health() {
    return Map.of(
        "status", "ok",
        "service", "mozilcode-cloud",
        "mode", "account + plans + usage + model catalog",
        "console", "/",
        "ops", "/ops",
        "docs", Map.of(
            "public_info", "/api/public/info",
            "auth_register", "POST /api/auth/register",
            "auth_login", "POST /api/auth/login",
            "dashboard", "GET /api/dashboard",
            "models", "GET /api/models",
            "admin_providers", "GET|POST /api/admin/providers",
            "admin_models", "GET|POST /api/admin/models",
            "gateway", "POST /api/gateway/chat/completions"
        )
    );
  }
}