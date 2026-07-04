package com.mewcode.cloud.model;

import com.mewcode.cloud.common.ApiResponses;
import com.mewcode.cloud.common.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ModelController {
  private final ModelService models;

  public ModelController(ModelService models) {
    this.models = models;
  }

  @GetMapping("/api/models")
  public Map<String, Object> list() {
    return Map.of("models", models.listActive());
  }

  @PutMapping("/api/user/model")
  public ResponseEntity<Map<String, Object>> selectModel(
      HttpServletRequest request,
      @RequestBody SelectModelRequest body
  ) {
    CurrentUser user = CurrentUser.from(request);
    if (body == null || body.modelId() == null) {
      return ResponseEntity.badRequest().body(ApiResponses.error("model_id required"));
    }

    return models.getById(body.modelId())
        .map(model -> {
          models.selectModel(user.id(), body.modelId());
          return ResponseEntity.ok(ApiResponses.ordered(
              "message", "model selected",
              "model", model
          ));
        })
        .orElseGet(() -> ResponseEntity.status(404).body(ApiResponses.error("model not found or inactive")));
  }

  public record SelectModelRequest(@com.fasterxml.jackson.annotation.JsonProperty("model_id") Integer modelId) {}
}
