package com.mewcode.cloud.plan;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SubscriptionInfo(
    int id,
    @JsonProperty("user_id") int userId,
    @JsonProperty("plan_id") int planId,
    @JsonProperty("plan_name") String planName,
    @JsonProperty("token_quota") long tokenQuota,
    @JsonProperty("token_used") long tokenUsed,
    @JsonProperty("expires_at") String expiresAt,
    @JsonProperty("is_active") boolean active
) {}
