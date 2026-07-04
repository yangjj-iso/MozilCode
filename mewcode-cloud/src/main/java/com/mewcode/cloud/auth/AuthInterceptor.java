package com.mewcode.cloud.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mewcode.cloud.common.ApiResponses;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuthInterceptor implements HandlerInterceptor {
  private final AuthService authService;
  private final ObjectMapper objectMapper;

  public AuthInterceptor(AuthService authService, ObjectMapper objectMapper) {
    this.authService = authService;
    this.objectMapper = objectMapper;
  }

  @Override
  public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
      throws IOException {
    if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
      return true;
    }

    String authHeader = request.getHeader("Authorization");
    if (authHeader == null || authHeader.isBlank()) {
      writeError(response, HttpStatus.UNAUTHORIZED, "missing authorization header");
      return false;
    }

    String[] parts = authHeader.split(" ", 2);
    if (parts.length != 2 || !"Bearer".equals(parts[0])) {
      writeError(response, HttpStatus.UNAUTHORIZED, "invalid authorization format");
      return false;
    }

    try {
      Claims claims = authService.parseToken(parts[1]);
      Object rawUserId = claims.get("user_id");
      if (!(rawUserId instanceof Number userId)) {
        writeError(response, HttpStatus.UNAUTHORIZED, "invalid user_id in token");
        return false;
      }
      request.setAttribute("user_id", userId.intValue());
      request.setAttribute("email", claims.get("email"));
      return true;
    } catch (Exception ignored) {
      writeError(response, HttpStatus.UNAUTHORIZED, "invalid token");
      return false;
    }
  }

  private void writeError(HttpServletResponse response, HttpStatus status, String message)
      throws IOException {
    response.setStatus(status.value());
    response.setContentType("application/json");
    response.setCharacterEncoding("UTF-8");
    objectMapper.writeValue(response.getWriter(), ApiResponses.error(message));
  }
}
