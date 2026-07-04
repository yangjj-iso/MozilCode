package com.mewcode.cloud;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {
  @GetMapping("/api/health")
  public Map<String, Object> health() {
    return Map.of(
        "status", "ok",
        "service", "mewcode-cloud",
        "mode", "bring-your-own-key + subscription"
    );
  }
}
