package com.mozilcode.cloud.common;

import jakarta.servlet.http.HttpServletRequest;

public record CurrentUser(int id, String email, String role) {
  public static CurrentUser from(HttpServletRequest request) {
    Object id = request.getAttribute("user_id");
    Object email = request.getAttribute("email");
    Object role = request.getAttribute("role");
    if (!(id instanceof Integer userId)) {
      throw new IllegalStateException("missing authenticated user");
    }
    return new CurrentUser(
        userId,
        email == null ? "" : email.toString(),
        role == null ? "user" : role.toString()
    );
  }

  public boolean isAdmin() {
    return "admin".equalsIgnoreCase(role);
  }

  public void requireAdmin() {
    if (!isAdmin()) {
      throw new ForbiddenException("admin only");
    }
  }

  public static class ForbiddenException extends RuntimeException {
    public ForbiddenException(String message) {
      super(message);
    }
  }
}