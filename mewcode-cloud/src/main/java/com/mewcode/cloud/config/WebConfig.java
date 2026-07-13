package com.mewcode.cloud.config;

import com.mewcode.cloud.auth.AuthInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.core.env.Environment;

@Configuration
public class WebConfig implements WebMvcConfigurer {
  private final AuthInterceptor authInterceptor;
  private final Environment environment;

  public WebConfig(AuthInterceptor authInterceptor, Environment environment) {
    this.authInterceptor = authInterceptor;
    this.environment = environment;
  }

  @Override
  public void addCorsMappings(CorsRegistry registry) {
    String origins = environment.getProperty(
        "mewcode.web.allowed-origins",
        "http://localhost:1420,http://127.0.0.1:1420"
    );
    registry.addMapping("/**")
        .allowedOrigins(origins.split(","))
        .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
        .allowedHeaders("Content-Type", "Authorization", "X-Api-Key")
        .exposedHeaders("X-RateLimit-Limit", "X-RateLimit-Remaining");
  }

  @Override
  public void addInterceptors(InterceptorRegistry registry) {
    registry.addInterceptor(authInterceptor)
        .addPathPatterns("/api/**")
        .excludePathPatterns("/api/health", "/api/auth/register", "/api/auth/login");
  }
}
