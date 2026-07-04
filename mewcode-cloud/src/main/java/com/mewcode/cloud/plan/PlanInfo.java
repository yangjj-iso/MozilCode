package com.mewcode.cloud.plan;

import com.fasterxml.jackson.annotation.JsonProperty;

public record PlanInfo(
    int id,
    String name,
    @JsonProperty("token_quota") long tokenQuota,
    @JsonProperty("duration_days") int durationDays,
    String description
) {}
