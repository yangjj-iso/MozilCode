package com.mewcode.cloud.config;

import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class CloudConfig {
  private final String jwtSecret;
  private final String dbUrl;
  private final String dbUser;
  private final String dbPassword;
  private final String dbDriver;

  public CloudConfig(Environment environment) {
    this.jwtSecret = settingOrDefault(
        environment,
        "mewcode.jwt.secret",
        "MEWCODE_JWT_SECRET",
        "mewcode-dev-secret-change-in-prod"
    );
    this.dbUrl = settingOrDefault(
        environment,
        "mewcode.db.url",
        "MEWCODE_DB_URL",
        "jdbc:mysql://127.0.0.1:3306/mewcode?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&useSSL=false"
    );
    this.dbUser = settingOrDefault(
        environment,
        "mewcode.db.user",
        "MEWCODE_DB_USER",
        "root"
    );
    this.dbPassword = settingOrDefault(
        environment,
        "mewcode.db.password",
        "MEWCODE_DB_PASSWORD",
        ""
    );
    this.dbDriver = settingOrDefault(
        environment,
        "mewcode.db.driver",
        "MEWCODE_DB_DRIVER",
        "com.mysql.cj.jdbc.Driver"
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

  private static String settingOrDefault(
      Environment environment,
      String propertyName,
      String envName,
      String fallback
  ) {
    String value = environment.getProperty(propertyName);
    if (value == null || value.isBlank()) {
      value = System.getenv(envName);
    }
    return value == null || value.isBlank() ? fallback : value;
  }
}
