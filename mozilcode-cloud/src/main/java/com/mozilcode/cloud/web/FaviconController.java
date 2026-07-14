package com.mozilcode.cloud.web;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class FaviconController {
  @GetMapping("/favicon.ico")
  public ResponseEntity<Void> favicon() {
    return ResponseEntity.noContent().build();
  }
}
