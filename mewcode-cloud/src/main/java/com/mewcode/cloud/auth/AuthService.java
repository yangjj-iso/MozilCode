package com.mewcode.cloud.auth;

import com.mewcode.cloud.config.CloudConfig;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.Optional;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
  private final JdbcTemplate db;
  private final CloudConfig config;
  private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

  public AuthService(JdbcTemplate db, CloudConfig config) {
    this.db = db;
    this.config = config;
  }

  public String hashPassword(String password) {
    return passwordEncoder.encode(password);
  }

  public boolean passwordMatches(String rawPassword, String hash) {
    return passwordEncoder.matches(rawPassword, hash);
  }

  public Optional<LoginUser> findLoginUser(String email) {
    try {
      return Optional.ofNullable(db.queryForObject(
          "SELECT id, email, password_hash FROM users WHERE email = ?",
          this::mapLoginUser,
          email
      ));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public String generateToken(int userId, String email) {
    Instant now = Instant.now();
    return Jwts.builder()
        .claim("user_id", userId)
        .claim("email", email)
        .issuedAt(Date.from(now))
        .expiration(Date.from(now.plus(72, ChronoUnit.HOURS)))
        .signWith(secretKey(), Jwts.SIG.HS256)
        .compact();
  }

  public Claims parseToken(String token) {
    return Jwts.parser()
        .verifyWith(secretKey())
        .build()
        .parseSignedClaims(token)
        .getPayload();
  }

  private SecretKey secretKey() {
    return new SecretKeySpec(config.jwtSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256");
  }

  private LoginUser mapLoginUser(ResultSet rs, int rowNum) throws SQLException {
    return new LoginUser(
        rs.getInt("id"),
        rs.getString("email"),
        rs.getString("password_hash")
    );
  }

  public record LoginUser(int id, String email, String passwordHash) {}
}
