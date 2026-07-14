package com.mozilcode.cloud.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.mozilcode.cloud.provider.ProviderService;
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
public class ModelService {
  private final JdbcTemplate db;
  private final ProviderService providers;

  public ModelService(JdbcTemplate db, ProviderService providers) {
    this.db = db;
    this.providers = providers;
  }

  /** User-facing catalog: no secrets, only active models with active providers. */
  public List<ModelInfo> listActiveForUsers() {
    return db.query("""
        SELECT m.id, m.name, m.display_name, m.provider, m.protocol, m.base_url, m.model_id,
               m.provider_id, m.is_active, m.sort_order, m.thinking, p.name AS provider_name
        FROM models m
        LEFT JOIN providers p ON p.id = m.provider_id
        WHERE m.is_active = 1 AND (p.id IS NULL OR p.is_active = 1)
        ORDER BY m.sort_order, m.id
        """, this::mapModel);
  }

  public List<ModelInfo> listAllForAdmin() {
    return db.query("""
        SELECT m.id, m.name, m.display_name, m.provider, m.protocol, m.base_url, m.model_id,
               m.provider_id, m.is_active, m.sort_order, m.thinking, p.name AS provider_name
        FROM models m
        LEFT JOIN providers p ON p.id = m.provider_id
        ORDER BY m.sort_order, m.id
        """, this::mapModel);
  }

  public Optional<ModelInfo> getById(int id) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT m.id, m.name, m.display_name, m.provider, m.protocol, m.base_url, m.model_id,
                 m.provider_id, m.is_active, m.sort_order, m.thinking, p.name AS provider_name
          FROM models m
          LEFT JOIN providers p ON p.id = m.provider_id
          WHERE m.id = ? AND m.is_active = 1 AND (p.id IS NULL OR p.is_active = 1)
          """, this::mapModel, id));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public Optional<ModelInfo> getByIdAny(int id) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT m.id, m.name, m.display_name, m.provider, m.protocol, m.base_url, m.model_id,
                 m.provider_id, m.is_active, m.sort_order, m.thinking, p.name AS provider_name
          FROM models m
          LEFT JOIN providers p ON p.id = m.provider_id
          WHERE m.id = ?
          """, this::mapModel, id));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  /**
   * Resolve a catalog model from client-requested model field.
   * Accepts internal name, display name, or upstream model_id.
   */
  public Optional<ModelInfo> resolveActive(String requested) {
    if (requested == null || requested.isBlank()) {
      return Optional.empty();
    }
    String key = requested.trim();
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT m.id, m.name, m.display_name, m.provider, m.protocol, m.base_url, m.model_id,
                 m.provider_id, m.is_active, m.sort_order, m.thinking, p.name AS provider_name
          FROM models m
          LEFT JOIN providers p ON p.id = m.provider_id
          WHERE m.is_active = 1
            AND (p.id IS NULL OR p.is_active = 1)
            AND (
              LOWER(m.name) = LOWER(?)
              OR LOWER(m.model_id) = LOWER(?)
              OR LOWER(m.display_name) = LOWER(?)
            )
          ORDER BY m.sort_order, m.id
          LIMIT 1
          """, this::mapModel, key, key, key));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public ModelInfo create(
      String name,
      String displayName,
      int providerId,
      String modelId,
      Boolean active,
      Integer sortOrder,
      Boolean thinking
  ) {
    var provider = providers.getRaw(providerId)
        .orElseThrow(() -> new ModelException(400, "provider not found"));
    if (name == null || name.isBlank()) {
      throw new ModelException(400, "name required");
    }
    if (displayName == null || displayName.isBlank()) {
      throw new ModelException(400, "display_name required");
    }
    if (modelId == null || modelId.isBlank()) {
      throw new ModelException(400, "model_id required");
    }
    GeneratedKeyHolder keyHolder = new GeneratedKeyHolder();
    db.update(connection -> {
      PreparedStatement ps = connection.prepareStatement("""
          INSERT INTO models (name, display_name, provider, protocol, base_url, model_id, provider_id, is_active, sort_order, thinking)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """, new String[] {"id"});
      ps.setString(1, name.trim());
      ps.setString(2, displayName.trim());
      ps.setString(3, provider.code());
      ps.setString(4, provider.protocol());
      ps.setString(5, provider.baseUrl());
      ps.setString(6, modelId.trim());
      ps.setInt(7, provider.id());
      ps.setInt(8, active == null || active ? 1 : 0);
      ps.setInt(9, sortOrder == null ? 0 : sortOrder);
      ps.setInt(10, thinking != null && thinking ? 1 : 0);
      return ps;
    }, keyHolder);
    Number id = keyHolder.getKey();
    if (id == null) {
      throw new ModelException(500, "failed to create model");
    }
    return getByIdAny(id.intValue()).orElseThrow(() -> new ModelException(500, "failed to load model"));
  }

  public ModelInfo update(
      int id,
      String name,
      String displayName,
      Integer providerId,
      String modelId,
      Boolean active,
      Integer sortOrder,
      Boolean thinking
  ) {
    ModelInfo current = getByIdAny(id).orElseThrow(() -> new ModelException(404, "model not found"));
    int nextProviderId = providerId == null
        ? (current.providerId() == null ? 0 : current.providerId())
        : providerId;
    var provider = providers.getRaw(nextProviderId)
        .orElseThrow(() -> new ModelException(400, "provider not found"));

    String nextName = name == null || name.isBlank() ? current.name() : name.trim();
    String nextDisplay = displayName == null || displayName.isBlank() ? current.displayName() : displayName.trim();
    String nextModelId = modelId == null || modelId.isBlank() ? current.modelId() : modelId.trim();
    boolean nextActive = active == null ? current.active() : active;
    int nextSort = sortOrder == null ? current.sortOrder() : sortOrder;
    boolean nextThinking = thinking == null ? current.thinking() : thinking;

    db.update("""
        UPDATE models
        SET name = ?, display_name = ?, provider = ?, protocol = ?, base_url = ?,
            model_id = ?, provider_id = ?, is_active = ?, sort_order = ?, thinking = ?
        WHERE id = ?
        """,
        nextName,
        nextDisplay,
        provider.code(),
        provider.protocol(),
        provider.baseUrl(),
        nextModelId,
        provider.id(),
        nextActive ? 1 : 0,
        nextSort,
        nextThinking ? 1 : 0,
        id
    );
    return getByIdAny(id).orElseThrow(() -> new ModelException(404, "model not found"));
  }

  public void delete(int id) {
    int deleted = db.update("DELETE FROM models WHERE id = ?", id);
    if (deleted == 0) {
      throw new ModelException(404, "model not found");
    }
    db.update("UPDATE users SET selected_model_id = NULL WHERE selected_model_id = ?", id);
  }

  private ModelInfo mapModel(ResultSet rs, int rowNum) throws SQLException {
    Object rawProviderId = rs.getObject("provider_id");
    Integer providerId = rawProviderId == null ? null : ((Number) rawProviderId).intValue();
    String providerName = null;
    try {
      providerName = rs.getString("provider_name");
    } catch (SQLException ignored) {
      // optional column
    }
    return new ModelInfo(
        rs.getInt("id"),
        rs.getString("name"),
        rs.getString("display_name"),
        rs.getString("provider"),
        providerName,
        rs.getString("protocol"),
        rs.getString("base_url"),
        rs.getString("model_id"),
        providerId,
        rs.getInt("is_active") == 1,
        rs.getInt("sort_order"),
        rs.getInt("thinking") == 1
    );
  }

  public record ModelInfo(
      int id,
      String name,
      @JsonProperty("display_name") String displayName,
      String provider,
      @JsonProperty("provider_name") String providerName,
      String protocol,
      @JsonProperty("base_url") String baseUrl,
      @JsonProperty("model_id") String modelId,
      @JsonProperty("provider_id") Integer providerId,
      @JsonProperty("is_active") boolean active,
      @JsonProperty("sort_order") int sortOrder,
      boolean thinking
  ) {}

  public static class ModelException extends RuntimeException {
    private final int status;

    public ModelException(int status, String message) {
      super(message);
      this.status = status;
    }

    public int status() {
      return status;
    }
  }
}
