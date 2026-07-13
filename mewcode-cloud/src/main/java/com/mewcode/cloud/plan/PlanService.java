package com.mewcode.cloud.plan;

import java.sql.PreparedStatement;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Optional;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanService {
  public static final DateTimeFormatter DB_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

  private final JdbcTemplate db;

  public PlanService(JdbcTemplate db) {
    this.db = db;
  }

  public List<PlanInfo> listPlans() {
    return db.query(
        "SELECT id, name, token_quota, duration_days, description FROM plans ORDER BY id",
        (rs, rowNum) -> new PlanInfo(
            rs.getInt("id"),
            rs.getString("name"),
            rs.getLong("token_quota"),
            rs.getInt("duration_days"),
            rs.getString("description")
        )
    );
  }

  @Transactional
  public RedeemResult redeem(int userId, String code) {
    RedeemCode redeemCode = findRedeemCode(code)
        .orElseThrow(() -> new RedeemException(404, "兑换码不存在"));
    if (redeemCode.usedByUserId() != null) {
      throw new RedeemException(409, "兑换码已被使用");
    }

    PlanInfo plan = getPlan(redeemCode.planId())
        .orElseThrow(() -> new RedeemException(500, "plan not found"));
    String expiresAt = LocalDateTime.now().plusDays(plan.durationDays()).format(DB_TIME);

    int claimed = db.update(
        "UPDATE redeem_codes SET used_by_user_id = ?, used_at = CURRENT_TIMESTAMP WHERE code = ? AND used_by_user_id IS NULL",
        userId,
        code
    );
    if (claimed == 0) {
      throw new RedeemException(409, "兑换码已被使用");
    }

    GeneratedKeyHolder keyHolder = new GeneratedKeyHolder();
    db.update(connection -> {
      PreparedStatement ps = connection.prepareStatement(
          "INSERT INTO subscriptions (user_id, plan_id, token_quota, expires_at) VALUES (?, ?, ?, ?)",
          new String[] {"id"}
      );
      ps.setInt(1, userId);
      ps.setInt(2, plan.id());
      ps.setLong(3, plan.tokenQuota());
      ps.setString(4, expiresAt);
      return ps;
    }, keyHolder);

    Number key = keyHolder.getKey();
    long subscriptionId = key == null ? 0 : key.longValue();
    return new RedeemResult(subscriptionId, plan.name(), plan.tokenQuota(), expiresAt);
  }

  public Optional<SubscriptionInfo> getActiveSubscription(int userId) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT s.id, s.user_id, s.plan_id, p.name, s.token_quota, s.token_used, s.expires_at
          FROM subscriptions s
          JOIN plans p ON s.plan_id = p.id
          WHERE s.user_id = ? AND s.expires_at > NOW()
          ORDER BY s.id DESC LIMIT 1
          """,
          (rs, rowNum) -> new SubscriptionInfo(
              rs.getInt("id"),
              rs.getInt("user_id"),
              rs.getInt("plan_id"),
              rs.getString("name"),
              rs.getLong("token_quota"),
              rs.getLong("token_used"),
              rs.getString("expires_at"),
              true
          ),
          userId
      ));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public boolean addUsage(int userId, int inputTokens, int outputTokens) {
    int total = inputTokens + outputTokens;
    int updated = db.update("""
        UPDATE subscriptions SET token_used = token_used + ?
        WHERE id = (
          SELECT id FROM subscriptions
          WHERE user_id = ? AND expires_at > NOW()
          ORDER BY id DESC LIMIT 1
        ) AND token_used + ? <= token_quota
        """, total, userId, total);
    return updated > 0;
  }

  public boolean hasQuota(int userId) {
    return getActiveSubscription(userId)
        .map(sub -> sub.tokenUsed() < sub.tokenQuota())
        .orElse(false);
  }

  private Optional<RedeemCode> findRedeemCode(String code) {
    try {
      return Optional.ofNullable(db.queryForObject(
          "SELECT plan_id, used_by_user_id FROM redeem_codes WHERE code = ?",
          (rs, rowNum) -> {
            Object usedBy = rs.getObject("used_by_user_id");
            return new RedeemCode(
                rs.getInt("plan_id"),
                usedBy == null ? null : ((Number) usedBy).longValue()
            );
          },
          code
      ));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  private Optional<PlanInfo> getPlan(int id) {
    try {
      return Optional.ofNullable(db.queryForObject(
          "SELECT id, name, token_quota, duration_days, description FROM plans WHERE id = ?",
          (rs, rowNum) -> new PlanInfo(
              rs.getInt("id"),
              rs.getString("name"),
              rs.getLong("token_quota"),
              rs.getInt("duration_days"),
              rs.getString("description")
          ),
          id
      ));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  private record RedeemCode(int planId, Long usedByUserId) {}

  public record RedeemResult(long id, String planName, long tokenQuota, String expiresAt) {}

  public static class RedeemException extends RuntimeException {
    private final int status;

    public RedeemException(int status, String message) {
      super(message);
      this.status = status;
    }

    public int status() {
      return status;
    }
  }
}
