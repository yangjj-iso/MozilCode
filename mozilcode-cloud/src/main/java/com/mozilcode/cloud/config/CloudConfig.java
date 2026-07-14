package com.mozilcode.cloud.config;

import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class CloudConfig {
  private static final String DEFAULT_PG_URL = "jdbc:postgresql://127.0.0.1:5432/mozilcode";

  private final String jwtSecret;
  private final String dbUrl;
  private final String dbUser;
  private final String dbPassword;
  private final String dbDriver;
  private final boolean production;

  public CloudConfig(Environment environment) {
    this.production = isProduction(environment);
    this.jwtSecret = settingOrDefault(
        environment,
        "mozilcode.jwt.secret",
        "MOZILCODE_JWT_SECRET",
        "mozilcode-dev-secret-change-in-prod",
        true
    );
    this.dbUrl = settingOrDefault(
        environment,
        "mozilcode.db.url",
        "MOZILCODE_DB_URL",
        DEFAULT_PG_URL,
        true
    );
    this.dbUser = settingOrDefault(
        environment,
        "mozilcode.db.user",
        "MOZILCODE_DB_USER",
        "postgres",
        false
    );
    this.dbPassword = settingOrDefault(
        environment,
        "mozilcode.db.password",
        "MOZILCODE_DB_PASSWORD",
        "postgres",
        false
    );
    this.dbDriver = settingOrDefault(
        environment,
        "mozilcode.db.driver",
        "MOZILCODE_DB_DRIVER",
        "org.postgresql.Driver",
        false
    );
  }

  public String jwtSecret() {
    return jwtSecret;
  }

  public String dbUrl() {
    return dbUrl;
  }

  public String dbUser() {
    return dbUser;
  }

  public String dbPassword() {
    return dbPassword;
  }

  public String dbDriver() {
    return dbDriver;
  }

  public boolean isProduction() {
    return production;
  }

  private String settingOrDefault(
      Environment environment,
      String propertyName,
      String envName,
      String fallback,
      boolean rejectDefaultInProduction
  ) {
    String value = environment.getProperty(propertyName);
    if (value == null || value.isBlank()) {
      value = System.getenv(envName);
    }
    value = value == null || value.isBlank() ? fallback : value;
    if (rejectDefaultInProduction && production && fallback.equals(value)) {
      throw new IllegalStateException(envName + " must be configured in production");
    }
    return value;
  }

  private static boolean isProduction(Environment environment) {
    String profile = environment.getProperty("spring.profiles.active", "");
    String env = environment.getProperty("mozilcode.environment", "");
    return profile.toLowerCase().contains("prod") || env.equalsIgnoreCase("production");
  }
}