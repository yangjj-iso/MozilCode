package com.mozilcode.cloud.common;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Explicitly retire user-side BYOK endpoints.
 * Provider keys are admin-managed only.
 */
@RestController
public class LegacyEndpointController {
  @RequestMapping({"/api/keys", "/api/keys/**"})
  public ResponseEntity<Map<String, Object>> keysRemoved() {
    return ResponseEntity.status(HttpStatus.GONE).body(ApiResponses.ordered(
        "error", "user provider keys are disabled",
        "message", "Models and API keys are managed by cloud admin. Use GET /api/models and POST /api/gateway/chat/completions."
    ));
  }
}