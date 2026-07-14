package com.mozilcode.cloud.web;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * React SPA 路由回退：非 API / 非静态资源路径一律交给 index.html。
 * 用户控制台与 /ops 管理端共用同一构建产物。
 */
@Controller
public class SpaForwardController {

  @GetMapping({
      "/models",
      "/models/",
      "/plans",
      "/plans/",
      "/usage",
      "/usage/",
      "/ops",
      "/ops/",
      "/ops/{*path}"
  })
  public String forwardSpa() {
    return "forward:/index.html";
  }
}