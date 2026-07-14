package com.mozilcode.cloud.model;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ModelController {
  private final ModelService models;

  public ModelController(ModelService models) {
    this.models = models;
  }

  /** Cloud catalog only. Local clients pick model themselves; no default-model selection. */
  @GetMapping("/api/models")
  public Map<String, Object> list() {
    return Map.of("models", models.listActiveForUsers());
  }
}