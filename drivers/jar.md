# 数据库 JDBC 驱动说明

本目录存放 admin-service 连接业务数据库所需的 JDBC 驱动 JAR 文件。
admin-service 通过 `URLClassLoader` 动态加载这些驱动，实现多数据库支持。

## 驱动文件清单

### ✅ 已包含的驱动

| 文件名               | 数据库类型     | 驱动类                              |
|---------------------|---------------|-------------------------------------|
| mysql-connector-j.jar| MySQL         | com.mysql.cj.jdbc.Driver            |
| postgresql.jar       | PostgreSQL    | org.postgresql.Driver               |
| mssql-jdbc.jar       | SQL Server    | com.microsoft.sqlserver.jdbc.SQLServerDriver |

### ❌ 缺失的驱动（需手动补充）

| 数据库类型     | 需要的 JAR 文件          | 驱动类                          | 获取方式                                                     |
|---------------|-------------------------|---------------------------------|-------------------------------------------------------------|
| Oracle        | ojdbc8.jar (或 ojdbc11.jar) | oracle.jdbc.OracleDriver       | [Maven Central](https://mvnrepository.com/artifact/com.oracle.database.jdbc/ojdbc8) |
| 达梦数据库 V8  | DmJdbcDriver18.jar       | dm.jdbc.driver.DmDriver          | 达梦官方安装包 `drivers/jdbc` 目录，或联系达梦技术支持获取         |

## 如何补充缺失的驱动

### 方式一：重新构建镜像（推荐，驱动打包进镜像）

1. 将缺失的 JAR 文件放入本目录（`drivers/`）
2. 重新构建 admin-service 镜像：
   ```bash
   bash deploy/build-images.sh
   ```
3. Dockerfile.admin 会执行 `COPY drivers/ /app/drivers/` 将驱动打包进镜像

### 方式二：通过管理后台上传（运行时动态添加）

1. 启动系统后，访问管理后台「驱动管理」页面
2. 上传 JAR 文件，选择对应的数据库类型
3. 上传的驱动会持久化到 Docker 命名卷 `drivers-data`，容器重启不丢失

> **注意**：方式二需要 docker-compose.yml 中 admin-service 已配置
> `drivers-data:/app/drivers` 卷挂载，否则容器重启后上传的驱动会丢失。

## 驱动与数据库类型映射

admin-service 的 `AdminController.DRIVER_PRESETS` 中定义了驱动类和 URL 模板：

| 数据库类型     | JDBC URL 模板                                          |
|---------------|--------------------------------------------------------|
| MySQL         | jdbc:mysql://{host}:{port}/{database}?useSSL=false...  |
| PostgreSQL    | jdbc:postgresql://{host}:{port}/{database}             |
| Oracle        | jdbc:oracle:thin:@{host}:{port}:{database}             |
| 达梦数据库V8   | jdbc:dm://{host}:{port}/{database}                     |
| SQL Server    | jdbc:sqlserver://{host}:{port};databaseName={database} |
