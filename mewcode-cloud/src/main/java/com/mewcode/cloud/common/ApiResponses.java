package com.mewcode.cloud.common;

import java.util.LinkedHashMap;
import java.util.Map;

public final class ApiResponses {
  private ApiResponses() {}

  public static Map<String, Object> error(String message) {
    return Map.of("error", message);
  }

  public static Map<String, Object> ordered(Object... pairs) {
    Map<String, Object> out = new LinkedHashMap<>();
    for (int i = 0; i + 1 < pairs.length; i += 2) {
      out.put(String.valueOf(pairs[i]), pairs[i + 1]);
    }
    return out;
  }
}
