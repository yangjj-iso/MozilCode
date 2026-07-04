package com.mewcode.cloud.model;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ModelInfo(
    int id,
    String name,
    @JsonProperty("display_name") String displayName,
    String provider,
    String protocol,
    @JsonProperty("base_url") String baseUrl,
    @JsonProperty("model_id") String modelId,
    @JsonProperty("is_active") boolean active,
    @JsonProperty("sort_order") int sortOrder
) {}
