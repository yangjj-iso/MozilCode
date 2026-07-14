package com.mozilcode.cloud.user;

import com.mozilcode.cloud.common.ApiResponses;
import com.mozilcode.cloud.common.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {
  @GetMapping("/api/user/profile")
  public ResponseEntity<Map<String, Object>> profile(HttpServletRequest request) {
    CurrentUser currentUser = CurrentUser.from(request);
    return ResponseEntity.ok(ApiResponses.ordered(
        "user_id", currentUser.id(),
        "email", currentUser.email(),
        "role", currentUser.role()
    ));
  }
}