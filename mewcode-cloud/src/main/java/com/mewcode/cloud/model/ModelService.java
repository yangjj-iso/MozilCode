package com.mewcode.cloud.model;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class ModelService {
  private final JdbcTemplate db;

  public ModelService(JdbcTemplate db) {
    this.db = db;
  }

  public List<ModelInfo> listActive() {
    return db.query("""
        SELECT id, name, display_name, provider, protocol, base_url, model_id, is_active, sort_order
        FROM models WHERE is_active = 1 ORDER BY sort_order, id
        """, this::mapModel);
  }

  public Optional<ModelInfo> getById(int id) {
    try {
      return Optional.ofNullable(db.queryForObject("""
          SELECT id, name, display_name, provider, protocol, base_url, model_id, is_active, sort_order
          FROM models WHERE id = ? AND is_active = 1
          """, this::mapModel, id));
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
  }

  public Optional<ModelInfo> getSelectedModel(int userId) {
    Integer modelId;
    try {
      modelId = db.queryForObject(
          "SELECT selected_model_id FROM users WHERE id = ?",
          Integer.class,
          userId
      );
    } catch (EmptyResultDataAccessException ignored) {
      return Optional.empty();
    }
    if (modelId == null) {
      return Optional.empty();
    }
    return getById(modelId);
  }

  public void selectModel(int userId, int modelId) {
    db.update(
        "UPDATE users SET selected_model_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        modelId,
        userId
    );
  }

  private ModelInfo mapModel(ResultSet rs, int rowNum) throws SQLException {
    return new ModelInfo(
        rs.getInt("id"),
        rs.getString("name"),
        rs.getString("display_name"),
        rs.getString("provider"),
        rs.getString("protocol"),
        rs.getString("base_url"),
        rs.getString("model_id"),
        rs.getInt("is_active") == 1,
        rs.getInt("sort_order")
    );
  }
}
