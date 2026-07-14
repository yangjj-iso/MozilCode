package com.mozilcode.cloud.common;

import com.mozilcode.cloud.model.ModelService;
import com.mozilcode.cloud.plan.PlanService;
import com.mozilcode.cloud.provider.ProviderService;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {
  @ExceptionHandler(HttpMessageNotReadableException.class)
  public ResponseEntity<Map<String, Object>> badJson() {
    return ResponseEntity.badRequest().body(ApiResponses.error("invalid request body"));
  }

  @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
  public ResponseEntity<Map<String, Object>> methodNotAllowed(HttpRequestMethodNotSupportedException e) {
    return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED)
        .body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(PlanService.RedeemException.class)
  public ResponseEntity<Map<String, Object>> redeem(PlanService.RedeemException e) {
    return ResponseEntity.status(e.status()).body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(ProviderService.ProviderException.class)
  public ResponseEntity<Map<String, Object>> provider(ProviderService.ProviderException e) {
    return ResponseEntity.status(e.status()).body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(ModelService.ModelException.class)
  public ResponseEntity<Map<String, Object>> model(ModelService.ModelException e) {
    return ResponseEntity.status(e.status()).body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(CurrentUser.ForbiddenException.class)
  public ResponseEntity<Map<String, Object>> forbidden(CurrentUser.ForbiddenException e) {
    return ResponseEntity.status(HttpStatus.FORBIDDEN).body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(IllegalStateException.class)
  public ResponseEntity<Map<String, Object>> illegalState(IllegalStateException e) {
    if ("missing authenticated user".equals(e.getMessage())) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(ApiResponses.error(e.getMessage()));
    }
    return ResponseEntity.internalServerError().body(ApiResponses.error(e.getMessage()));
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<Map<String, Object>> unexpected(Exception e) {
    String message = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
    return ResponseEntity.internalServerError().body(ApiResponses.error(message));
  }
}