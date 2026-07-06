package com.assessment.admin;

import com.zaxxer.hikari.HikariDataSource;
import jakarta.persistence.EntityManagerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;
import org.springframework.transaction.PlatformTransactionManager;

import javax.sql.DataSource;
import java.util.HashMap;
import java.util.Map;

@Configuration
@EnableJpaRepositories(basePackages = "com.assessment.admin.repository")
public class DataSourceConfig {

    @Value("${db.type:mysql}")
    private String dbType;

    // ───────── MySQL ─────────
    @Value("${db.mysql.host:localhost}")
    private String mysqlHost;
    @Value("${db.mysql.port:3306}")
    private int mysqlPort;
    @Value("${db.mysql.database:assessment}")
    private String mysqlDb;
    @Value("${db.mysql.user:root}")
    private String mysqlUser;
    @Value("${db.mysql.password:root}")
    private String mysqlPassword;

    // ───────── PostgreSQL ─────────
    @Value("${db.postgresql.host:localhost}")
    private String pgHost;
    @Value("${db.postgresql.port:5432}")
    private int pgPort;
    @Value("${db.postgresql.database:assessment}")
    private String pgDb;
    @Value("${db.postgresql.user:postgres}")
    private String pgUser;
    @Value("${db.postgresql.password:postgres}")
    private String pgPassword;

    @Bean
    @Primary
    public DataSource dataSource() {
        HikariDataSource ds = new HikariDataSource();
        if ("h2".equalsIgnoreCase(dbType)) {
            ds.setJdbcUrl("jdbc:h2:mem:assessment;DB_CLOSE_DELAY=-1;MODE=MySQL");
            ds.setDriverClassName("org.h2.Driver");
            ds.setUsername("sa");
            ds.setPassword("");
        } else if ("postgresql".equalsIgnoreCase(dbType)) {
            ds.setJdbcUrl(String.format("jdbc:postgresql://%s:%d/%s", pgHost, pgPort, pgDb));
            ds.setDriverClassName("org.postgresql.Driver");
            ds.setUsername(pgUser);
            ds.setPassword(pgPassword);
        } else {
            // 默认 MySQL
            ds.setJdbcUrl(String.format(
                    "jdbc:mysql://%s:%d/%s?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&connectionCollation=utf8mb4_unicode_ci&sessionVariables=character_set_client=utf8mb4,character_set_connection=utf8mb4,character_set_results=utf8mb4",
                    mysqlHost, mysqlPort, mysqlDb));
            ds.setDriverClassName("com.mysql.cj.jdbc.Driver");
            ds.setUsername(mysqlUser);
            ds.setPassword(mysqlPassword);
        }
        return ds;
    }

    @Bean
    @Primary
    public LocalContainerEntityManagerFactoryBean entityManagerFactory(DataSource dataSource) {
        LocalContainerEntityManagerFactoryBean emf = new LocalContainerEntityManagerFactoryBean();
        emf.setDataSource(dataSource);
        emf.setPackagesToScan("com.assessment.admin.model");

        HibernateJpaVendorAdapter adapter = new HibernateJpaVendorAdapter();
        if ("postgresql".equalsIgnoreCase(dbType)) {
            adapter.setDatabasePlatform("org.hibernate.dialect.PostgreSQLDialect");
        } else if ("h2".equalsIgnoreCase(dbType)) {
            adapter.setDatabasePlatform("org.hibernate.dialect.H2Dialect");
        } else {
            adapter.setDatabasePlatform("org.hibernate.dialect.MySQLDialect");
        }
        emf.setJpaVendorAdapter(adapter);

        Map<String, Object> props = new HashMap<>();
        props.put("hibernate.format_sql", true);
        props.put("hibernate.hbm2ddl.auto", "update");
        props.put("hibernate.connection.characterEncoding", "UTF-8");
        props.put("hibernate.connection.useUnicode", "true");
        props.put("hibernate.connection.charSet", "UTF-8");
        if ("postgresql".equalsIgnoreCase(dbType)) {
            props.put("hibernate.dialect", "org.hibernate.dialect.PostgreSQLDialect");
        } else if ("h2".equalsIgnoreCase(dbType)) {
            props.put("hibernate.dialect", "org.hibernate.dialect.H2Dialect");
        } else {
            props.put("hibernate.dialect", "org.hibernate.dialect.MySQLDialect");
        }
        emf.setJpaPropertyMap(props);
        return emf;
    }

    @Bean
    @Primary
    public PlatformTransactionManager transactionManager(EntityManagerFactory emf) {
        return new JpaTransactionManager(emf);
    }
}
