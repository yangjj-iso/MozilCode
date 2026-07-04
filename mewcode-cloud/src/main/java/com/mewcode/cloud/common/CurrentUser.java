package com.mewcode.cloud.common;

import jakarta.servlet.http.HttpServletRequest;

public record CurrentUser(int id, String email) {
  public static CurrentUser from(HttpServletRequest request) {
    Object id = request.getAttribute("user_id");
    Object email = request.getAttribute("email");
    if (!(id instanceof Integer userId)) {
      throw new IllegalStateException("missing authenticated user");
    }
    return new CurrentUser(userId, email == null ? "" : email.toString());
  }
}
