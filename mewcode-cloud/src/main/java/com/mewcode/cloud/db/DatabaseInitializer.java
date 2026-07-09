package com.mewcode.cloud.db;

import jakarta.annotation.PostConstruct;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class DatabaseInitializer {
  private final JdbcTemplate db;

  public DatabaseInitializer(JdbcTemplate db) {
    this.db = db;
  }

  @PostConstruct
  public void initialize() {
    migrate();
    seedDefaults();
  }

  private void migrate() {
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INT PRIMARY KEY AUTO_INCREMENT,
          email VARCHAR(255) UNIQUE NOT NULL,
          password_hash VARCHAR(255) NOT NULL,
          selected_model_id INT DEFAULT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """);

    db.execute("""
        CREATE TABLE IF NOT EXISTS models (
          id INT PRIMARY KEY AUTO_INCREMENT,
          name VARCHAR(255) NOT NULL,
          display_name VARCHAR(255) NOT NULL,
          provider VARCHAR(64) NOT NULL,
          protocol VARCHAR(64) NOT NULL,
          base_url VARCHAR(512) NOT NULL,
          model_id VARCHAR(255) NOT NULL,
          is_active TINYINT DEFAULT 1,
          sort_order INT DEFAULT 0,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """);

    db.execute("""
        CREATE TABLE IF NOT EXISTS plans (
          id INT PRIMARY KEY AUTO_INCREMENT,
          name VARCHAR(255) NOT NULL,
          token_quota BIGINT NOT NULL,
          duration_days INT NOT NULL,
          description VARCHAR(255) DEFAULT '',
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """);

    db.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
          code VARCHAR(128) PRIMARY KEY,
          plan_id INT NOT NULL,
          used_by_user_id INT DEFAULT NULL,
          used_at DATETIME DEFAULT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
        """);

    db.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
          id INT PRIMARY KEY AUTO_INCREMENT,
          user_id INT NOT NULL,
          plan_id INT NOT NULL,
          token_quota BIGINT NOT NULL,
          token_used BIGINT DEFAULT 0,
          expires_at DATETIME NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id),
          FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
        """);

    db.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
          id INT PRIMARY KEY AUTO_INCREMENT,
          user_id INT NOT NULL,
          model VARCHAR(255) NOT NULL,
          input_tokens BIGINT DEFAULT 0,
          output_tokens BIGINT DEFAULT 0,
          latency_ms BIGINT DEFAULT 0,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """);
  }

  private void seedDefaults() {
    if (count("models") == 0) {
      Object[][] models = {
          {"stepfun-flash", "StepFun Flash", "stepfun", "openai", "https://api.stepfun.com/step_plan/v1", "step-3.7-flash", 0},
          {"deepseek-chat", "DeepSeek Chat", "deepseek", "openai", "https://api.deepseek.com/v1", "deepseek-chat", 1},
          {"qwen-plus", "Qwen Plus", "qwen", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", 2},
      };
      for (Object[] model : models) {
        db.update("""
            INSERT INTO models (name, display_name, provider, protocol, base_url, model_id, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, model);
      }
    }

    if (count("plans") == 0) {
      db.update("""
          INSERT INTO plans (name, token_quota, duration_days, description)
          VALUES (?, ?, ?, ?)
          """, "体验套餐", 500_000L, 30, "50万 token，30天有效");
      db.update("""
          INSERT INTO plans (name, token_quota, duration_days, description)
          VALUES (?, ?, ?, ?)
          """, "标准套餐", 5_000_000L, 30, "500万 token，30天有效");
    }

    if (count("redeem_codes") == 0) {
      db.update("INSERT INTO redeem_codes (code, plan_id) VALUES (?, ?)", "MEWCODE-FREE-500K", 1);
      db.update("INSERT INTO redeem_codes (code, plan_id) VALUES (?, ?)", "MEWCODE-PRO-5M", 2);
    }
  }

  private int count(String tableName) {
    Integer count = db.queryForObject("SELECT COUNT(*) FROM " + tableName, Integer.class);
    return count == null ? 0 : count;
  }
}
