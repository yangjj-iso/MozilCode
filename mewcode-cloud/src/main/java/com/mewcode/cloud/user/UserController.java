package com.mewcode.cloud.user;

import com.mewcode.cloud.common.ApiResponses;
import com.mewcode.cloud.common.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Map;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {
  private final JdbcTemplate db;

  public UserController(JdbcTemplate db) {
    this.db = db;
  }

  @GetMapping("/api/user/profile")
  public ResponseEntity<Map<String, Object>> profile(HttpServletRequest request) {
    CurrentUser currentUser = CurrentUser.from(request);
    try {
      UserProfile profile = db.queryForObject(
          "SELECT email, selected_model_id FROM users WHERE id = ?",
          this::mapProfile,
          currentUser.id()
      );
      Map<String, Object> out = ApiResponses.ordered(
          "user_id", currentUser.id(),
          "email", profile.email(),
          "selected_model_id", profile.selectedModelId()
      );
      if (profile.selectedModelId() != null) {
        selectedModel(profile.selectedModelId()).ifPresent(model -> out.put("selected_model", model));
      }
      return ResponseEntity.ok(out);
    } catch (EmptyResultDataAccessException ignored) {
      return ResponseEntity.status(404).body(ApiResponses.error("not found"));
    }
  }

  private java.util.Optional<Map<String, Object>> selectedModel(long modelId) {
    try {
      return java.util.Optional.ofNullable(db.queryForObject(
          "SELECT name, display_name FROM models WHERE id = ?",
          (rs, rowNum) -> ApiResponses.ordered(
              "id", modelId,
              "name", rs.getString("name"),
              "display_name", rs.getString("display_name")
          ),
          modelId
      ));
    } catch (EmptyResultDataAccessException ignored) {
      return java.util.Optional.empty();
    }
  }

  private UserProfile mapProfile(ResultSet rs, int rowNum) throws SQLException {
    Object rawSelectedModel = rs.getObject("selected_model_id");
    Long selectedModelId = rawSelectedModel == null ? null : ((Number) rawSelectedModel).longValue();
    return new UserProfile(rs.getString("email"), selectedModelId);
  }

  private record UserProfile(String email, Long selectedModelId) {}
}
