package com.mozilcode.cloud.config;

import javax.sql.DataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

@Configuration
@EnableTransactionManagement
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

  @Bean
  public PlatformTransactionManager transactionManager(DataSource dataSource) {
    return new DataSourceTransactionManager(dataSource);
  }
}
