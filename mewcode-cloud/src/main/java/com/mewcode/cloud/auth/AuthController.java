package com.mewcode.cloud.auth;

import com.mewcode.cloud.common.ApiResponses;
import java.net.URI;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
  private static final Pattern EMAIL = Pattern.compile("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$");

  private final JdbcTemplate db;
  private final AuthService authService;

  public AuthController(JdbcTemplate db, AuthService authService) {
    this.db = db;
    this.authService = authService;
  }

  @PostMapping("/register")
  public ResponseEntity<Map<String, Object>> register(@RequestBody RegisterRequest request) {
    if (request.email() == null || !EMAIL.matcher(request.email()).matches()) {
      return ResponseEntity.badRequest().body(ApiResponses.error("invalid email"));
    }
    if (request.password() == null || request.password().length() < 6) {
      return ResponseEntity.badRequest().body(ApiResponses.error("password must be at least 6 characters"));
    }

    try {
      db.update(
          "INSERT INTO users (email, password_hash) VALUES (?, ?)",
          request.email(),
          authService.hashPassword(request.password())
      );
      return ResponseEntity.created(URI.create("/api/auth/login"))
          .body(Map.of("message", "registered"));
    } catch (DataIntegrityViolationException e) {
      String message = e.getMessage() == null ? "" : e.getMessage();
      if (message.contains("UNIQUE")) {
        return ResponseEntity.status(409).body(ApiResponses.error("email already registered"));
      }
      return ResponseEntity.internalServerError().body(ApiResponses.error(message));
    } catch (Exception e) {
      return ResponseEntity.internalServerError().body(ApiResponses.error(e.getMessage()));
    }
  }

  @PostMapping("/login")
  public ResponseEntity<Map<String, Object>> login(@RequestBody LoginRequest request) {
    if (request.email() == null || request.password() == null) {
      return ResponseEntity.badRequest().body(ApiResponses.error("email and password required"));
    }

    return authService.findLoginUser(request.email())
        .filter(user -> authService.passwordMatches(request.password(), user.passwordHash()))
        .map(user -> ResponseEntity.ok(ApiResponses.ordered(
            "token", authService.generateToken(user.id(), user.email()),
            "user_id", user.id(),
            "email", user.email()
        )))
        .orElseGet(() -> ResponseEntity.status(401).body(ApiResponses.error("invalid credentials")));
  }

  public record RegisterRequest(String email, String password) {}

  public record LoginRequest(String email, String password) {}
}
