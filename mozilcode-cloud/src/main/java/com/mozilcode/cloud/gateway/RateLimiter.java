package com.mozilcode.cloud.gateway;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

@Component
public class RateLimiter {
  private static final int LIMIT = 60;
  private static final Duration WINDOW = Duration.ofMinutes(1);

  private final Map<Integer, Bucket> buckets = new ConcurrentHashMap<>();

  public Result check(int userId) {
    Instant now = Instant.now();
    Bucket bucket = buckets.compute(userId, (id, existing) -> {
      if (existing == null || now.isAfter(existing.resetAt())) {
        return new Bucket(1, now.plus(WINDOW));
      }
      return new Bucket(existing.count() + 1, existing.resetAt());
    });

    boolean allowed = bucket.count() <= LIMIT;
    int remaining = Math.max(0, LIMIT - bucket.count());
    return new Result(allowed, LIMIT, remaining, bucket.resetAt(), WINDOW);
  }

  public record Result(boolean allowed, int limit, int remaining, Instant resetAt, Duration window) {}

  private record Bucket(int count, Instant resetAt) {}
}
