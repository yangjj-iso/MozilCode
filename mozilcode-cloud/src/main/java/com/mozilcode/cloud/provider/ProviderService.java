package com.mozilcode.cloud.provider;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;

@Service
public class ProviderService {
  private final JdbcTemplate db;

  public ProviderService(JdbcTemplate db) {
    this.db = db;
  }

  public List<ProviderView> listAll() {
    return db.query("""
        SELECT id, code, name, protocol, base_url, api_key, is_active, sort_order, created_at, updated_at
        FROM providers
        ORDER BY sort_order, id
        """, (rs, rowNum) -> mapView(rs, true));
  }

  public List<ProviderView> listActivePublic() {
    return db.query("""
        SELECT id, code, name, protocol, base_url, api_key, is_active, sort_order, created_at, updated_at
        FROM providers
        WHERE is_active = 1
        ORDER BY sort_order, id
        """, (rs, rowNum) -> mapView(rs, false));
  }

  public Optional<ProviderRaw> getRaw(int id) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT id, code, name, protocol, base_url, api_key, is_active, sort_order
          FROM providers WHERE id = ?
          """, this::mapRaw, id));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public Optional<ProviderRaw> getRawByCode(String code) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT id, code, name, protocol, base_url, api_key, is_active, sort_order
          FROM providers WHERE LOWER(code) = LOWER(?)
          """, this::mapRaw, code));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public ProviderView create(String code, String name, String protocol, String baseUrl, String apiKey, boolean active, int sortOrder) {
    if (code == null || code.isBlank()) {
      throw new ProviderException(400, "code required");
    }
    if (name == null || name.isBlank()) {
      throw new ProviderException(400, "name required");
    }
    if (baseUrl == null || baseUrl.isBlank()) {
      throw new ProviderException(400, "base_url required");
    }
    String normalizedCode = code.trim().toLowerCase();
    String normalizedProtocol = protocol == null || protocol.isBlank() ? "openai" : protocol.trim().toLowerCase();
    GeneratedKeyHolder keyHolder = new GeneratedKeyHolder();
    try {
      db.update(connection -> {
        PreparedStatement ps = connection.prepareStatement("""
            INSERT INTO providers (code, name, protocol, base_url, api_key, is_active, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, new String[] {"id"});
        ps.setString(1, normalizedCode);
        ps.setString(2, name.trim());
        ps.setString(3, normalizedProtocol);
        ps.setString(4, baseUrl.trim());
        ps.setString(5, apiKey == null ? "" : apiKey.trim());
        ps.setInt(6, active ? 1 : 0);
        ps.setInt(7, sortOrder);
        return ps;
      }, keyHolder);
    } catch (Exception e) {
      throw new ProviderException(409, "provider code already exists or invalid");
    }
    Number id = keyHolder.getKey();
    if (id == null) {
      throw new ProviderException(500, "failed to create provider");
    }
    return getView(id.intValue()).orElseThrow(() -> new ProviderException(500, "failed to load provider"));
  }

  public ProviderView update(int id, String name, String protocol, String baseUrl, String apiKey, Boolean active, Integer sortOrder) {
    ProviderRaw current = getRaw(id).orElseThrow(() -> new ProviderException(404, "provider not found"));
    String nextName = name == null || name.isBlank() ? current.name() : name.trim();
    String nextProtocol = protocol == null || protocol.isBlank() ? current.protocol() : protocol.trim().toLowerCase();
    String nextBaseUrl = baseUrl == null || baseUrl.isBlank() ? current.baseUrl() : baseUrl.trim();
    String nextKey = apiKey == null ? current.apiKey() : apiKey.trim();
    boolean nextActive = active == null ? current.active() : active;
    int nextSort = sortOrder == null ? current.sortOrder() : sortOrder;

    db.update("""
        UPDATE providers
        SET name = ?, protocol = ?, base_url = ?, api_key = ?, is_active = ?, sort_order = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, nextName, nextProtocol, nextBaseUrl, nextKey, nextActive ? 1 : 0, nextSort, id);

    // Keep denormalized model fields in sync.
    db.update("""
        UPDATE models SET protocol = ?, base_url = ?, provider = ?
        WHERE provider_id = ?
        """, nextProtocol, nextBaseUrl, current.code(), id);

    return getView(id).orElseThrow(() -> new ProviderException(404, "provider not found"));
  }

  public void delete(int id) {
    Integer modelCount = db.queryForObject(
        "SELECT COUNT(*) FROM models WHERE provider_id = ?",
        Integer.class,
        id
    );
    if (modelCount != null && modelCount > 0) {
      throw new ProviderException(409, "provider has models; delete or reassign models first");
    }
    int deleted = db.update("DELETE FROM providers WHERE id = ?", id);
    if (deleted == 0) {
      throw new ProviderException(404, "provider not found");
    }
  }

  private Optional<ProviderView> getView(int id) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT id, code, name, protocol, base_url, api_key, is_active, sort_order, created_at, updated_at
          FROM providers WHERE id = ?
          """, (rs, rowNum) -> mapView(rs, true), id));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  private ProviderView mapView(ResultSet rs, boolean includeMaskedKey) throws SQLException {
    String key = rs.getString("api_key");
    return new ProviderView(
        rs.getInt("id"),
        rs.getString("code"),
        rs.getString("name"),
        rs.getString("protocol"),
        rs.getString("base_url"),
        includeMaskedKey ? mask(key) : null,
        includeMaskedKey && key != null && !key.isBlank(),
        rs.getInt("is_active") == 1,
        rs.getInt("sort_order"),
        rs.getString("created_at"),
        rs.getString("updated_at")
    );
  }

  private ProviderRaw mapRaw(ResultSet rs, int rowNum) throws SQLException {
    return new ProviderRaw(
        rs.getInt("id"),
        rs.getString("code"),
        rs.getString("name"),
        rs.getString("protocol"),
        rs.getString("base_url"),
        rs.getString("api_key"),
        rs.getInt("is_active") == 1,
        rs.getInt("sort_order")
    );
  }

  static String mask(String apiKey) {
    if (apiKey == null || apiKey.isBlank()) {
      return "";
    }
    String value = apiKey.trim();
    if (value.length() <= 8) {
      return "****";
    }
    return value.substring(0, 4) + "..." + value.substring(value.length() - 4);
  }

  public record ProviderView(
      int id,
      String code,
      String name,
      String protocol,
      @JsonProperty("base_url") String baseUrl,
      @JsonProperty("api_key_masked") String apiKeyMasked,
      @JsonProperty("has_api_key") Boolean hasApiKey,
      @JsonProperty("is_active") boolean active,
      @JsonProperty("sort_order") int sortOrder,
      @JsonProperty("created_at") String createdAt,
      @JsonProperty("updated_at") String updatedAt
  ) {}

  public record ProviderRaw(
      int id,
      String code,
      String name,
      String protocol,
      String baseUrl,
      String apiKey,
      boolean active,
      int sortOrder
  ) {}

  public static class ProviderException extends RuntimeException {
    private final int status;

    public ProviderException(int status, String message) {
      super(message);
      this.status = status;
    }

    public int status() {
      return status;
    }
  }
}