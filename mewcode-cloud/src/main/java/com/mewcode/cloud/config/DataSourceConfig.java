package com.mewcode.cloud.config;

import javax.sql.DataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

@Configuration
public class DataSourceConfig {
  @Bean
  public DataSource dataSource(CloudConfig config) {
    DriverManagerDataSource ds = new DriverManagerDataSource();
    ds.setDriverClassName(config.dbDriver());
    ds.setUrl(config.dbUrl());
    ds.setUsername(config.dbUser());
    ds.setPassword(config.dbPassword());
    return ds;
  }
}
