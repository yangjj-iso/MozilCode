package com.mewcode.cloud.usage;

import com.mewcode.cloud.common.ApiResponses;
import com.mewcode.cloud.common.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UsageController {
  private final JdbcTemplate db;

  public UsageController(JdbcTemplate db) {
    this.db = db;
  }

  @GetMapping("/api/usage")
  public ResponseEntity<Map<String, Object>> stats(HttpServletRequest request) {
    CurrentUser user = CurrentUser.from(request);
    try {
      List<Map<String, Object>> byModel = db.query("""
          SELECT model, COALESCE(SUM(input_tokens),0) AS total_input,
                 COALESCE(SUM(output_tokens),0) AS total_output, COUNT(*) AS total_requests
          FROM usage_log WHERE user_id = ?
          GROUP BY model ORDER BY SUM(input_tokens+output_tokens) DESC
          """,
          (rs, rowNum) -> ApiResponses.ordered(
              "model", rs.getString("model"),
              "total_input_tokens", rs.getLong("total_input"),
              "total_output_tokens", rs.getLong("total_output"),
              "total_requests", rs.getLong("total_requests")
          ),
          user.id()
      );

      long totalInput = 0;
      long totalOutput = 0;
      long totalRequests = 0;
      for (Map<String, Object> item : byModel) {
        totalInput += ((Number) item.get("total_input_tokens")).longValue();
        totalOutput += ((Number) item.get("total_output_tokens")).longValue();
        totalRequests += ((Number) item.get("total_requests")).longValue();
      }

      List<Map<String, Object>> daily = dailyUsage(user.id());
      return ResponseEntity.ok(ApiResponses.ordered(
          "by_model", byModel,
          "daily", daily,
          "total_input", totalInput,
          "total_output", totalOutput,
          "total_tokens", totalInput + totalOutput,
          "total_requests", totalRequests
      ));
    } catch (Exception e) {
      return ResponseEntity.internalServerError().body(ApiResponses.error(e.getMessage()));
    }
  }

  private List<Map<String, Object>> dailyUsage(int userId) {
    try {
      return db.query("""
          SELECT DATE(created_at) AS d, COALESCE(SUM(input_tokens),0) AS input_tokens,
                 COALESCE(SUM(output_tokens),0) AS output_tokens, COUNT(*) AS requests
          FROM usage_log WHERE user_id = ? AND created_at > datetime('now', '-7 days')
          GROUP BY d ORDER BY d DESC
          """,
          (rs, rowNum) -> ApiResponses.ordered(
              "date", rs.getString("d"),
              "input_tokens", rs.getLong("input_tokens"),
              "output_tokens", rs.getLong("output_tokens"),
              "requests", rs.getLong("requests")
          ),
          userId
      );
    } catch (Exception ignored) {
      return new ArrayList<>();
    }
  }
}
