# 将运行中的管理服务（H2）元数据迁移到本机 MySQL。
param(
    [string]$AdminUrl = "http://localhost:10258/api/admin",
    [string]$MysqlHost = "127.0.0.1",
    [int]$MysqlPort = 3306,
    [string]$MysqlDatabase = "assessment",
    [string]$MysqlUser = "root",
    [string]$MysqlPassword = "root",
    [string]$DataSourcePassword = "root"
)

$ErrorActionPreference = "Stop"

function ConvertTo-SqlValue([AllowNull()][object]$Value) {
    if ($null -eq $Value) { return "NULL" }
    $text = [string]$Value
    $text = $text.Replace("\", "\\").Replace("'", "''").Replace("`r", "\r").Replace("`n", "\n")
    return "'$text'"
}

function ConvertTo-SqlDate([AllowNull()][object]$Value) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return "NULL" }
    return ConvertTo-SqlValue ([datetime]::Parse([string]$Value).ToString("yyyy-MM-dd HH:mm:ss"))
}

$mysqlExe = @(
    "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
    "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
    "mysql.exe"
) | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1

if (-not $mysqlExe) { throw "未找到 mysql.exe" }

$databaseResponse = Invoke-RestMethod -Uri "$AdminUrl/database/list" -Method Get
$datasetResponse = Invoke-RestMethod -Uri "$AdminUrl/dataset/list" -Method Get
$llmResponse = Invoke-RestMethod -Uri "$AdminUrl/config/llm/list" -Method Get

$databases = @($databaseResponse.databases)
$datasets = @($datasetResponse.datasets)
$llmConfigs = @($llmResponse.configs)

if ($databases.Count -ne 1) {
    throw "当前迁移脚本要求恰好 1 条数据库配置，实际为 $($databases.Count) 条"
}
if ($datasets.Count -ne 7) {
    throw "当前迁移脚本要求恰好 7 条数据集配置，实际为 $($datasets.Count) 条"
}

$sql = [System.Collections.Generic.List[string]]::new()
$sql.Add("SET NAMES utf8mb4;")
$sql.Add("START TRANSACTION;")

foreach ($database in $databases) {
    $values = @(
        (ConvertTo-SqlValue $database.id),
        (ConvertTo-SqlValue $database.name),
        (ConvertTo-SqlValue $database.type),
        (ConvertTo-SqlValue $database.host),
        ([string][int]$database.port),
        (ConvertTo-SqlValue $database.database),
        (ConvertTo-SqlValue $database.username),
        (ConvertTo-SqlValue $DataSourcePassword),
        (ConvertTo-SqlValue $database.status),
        (ConvertTo-SqlValue $database.dbVersion),
        (ConvertTo-SqlValue $database.latency),
        (ConvertTo-SqlValue $database.errorMsg),
        (ConvertTo-SqlDate $database.createTime),
        "NOW()"
    ) -join ","
    $sql.Add(@"
INSERT INTO ass_database_config
    (id,name,type,host,port,db_name,username,password,status,db_version,latency,error_msg,create_time,update_time)
VALUES ($values)
ON DUPLICATE KEY UPDATE
    name=VALUES(name),type=VALUES(type),host=VALUES(host),port=VALUES(port),
    db_name=VALUES(db_name),username=VALUES(username),password=VALUES(password),
    status=VALUES(status),db_version=VALUES(db_version),latency=VALUES(latency),
    error_msg=VALUES(error_msg),update_time=NOW();
"@)
}

foreach ($dataset in $datasets) {
    $records = if ($null -eq $dataset.records) { 0 } else { [int]$dataset.records }
    $values = @(
        (ConvertTo-SqlValue $dataset.id),
        (ConvertTo-SqlValue $dataset.name),
        (ConvertTo-SqlValue $dataset.description),
        (ConvertTo-SqlValue $dataset.databaseId),
        (ConvertTo-SqlValue $dataset.tableName),
        (ConvertTo-SqlValue $dataset.sql),
        ([string]$records),
        (ConvertTo-SqlDate $dataset.lastExecuted),
        (ConvertTo-SqlDate $dataset.createTime),
        "NOW()"
    ) -join ","
    $sql.Add(@"
INSERT INTO ass_dataset
    (id,name,description,database_id,table_name,sql_text,records,last_executed,create_time,update_time)
VALUES ($values)
ON DUPLICATE KEY UPDATE
    name=VALUES(name),description=VALUES(description),database_id=VALUES(database_id),
    table_name=VALUES(table_name),sql_text=VALUES(sql_text),records=VALUES(records),
    last_executed=VALUES(last_executed),update_time=NOW();
"@)
}

foreach ($config in $llmConfigs) {
    $isActive = if ($config.isActive) { 1 } else { 0 }
    $temperature = if ($null -eq $config.temperature) { "NULL" } else { [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $config.temperature) }
    $maxTokens = if ($null -eq $config.maxTokens) { "NULL" } else { [string][int]$config.maxTokens }
    $topP = if ($null -eq $config.topP) { "NULL" } else { [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $config.topP) }
    $values = @(
        (ConvertTo-SqlValue $config.id),
        (ConvertTo-SqlValue $config.name),
        (ConvertTo-SqlValue $config.type),
        (ConvertTo-SqlValue $config.apiUrl),
        (ConvertTo-SqlValue $config.apiKey),
        (ConvertTo-SqlValue $config.model),
        $temperature,
        $maxTokens,
        $topP,
        ([string]$isActive),
        (ConvertTo-SqlDate $config.createTime),
        "NOW()"
    ) -join ","
    $sql.Add(@"
INSERT INTO ass_llm_config
    (id,name,llm_type,api_url,api_key,model,temperature,max_tokens,top_p,is_active,create_time,update_time)
VALUES ($values)
ON DUPLICATE KEY UPDATE
    name=VALUES(name),llm_type=VALUES(llm_type),api_url=VALUES(api_url),
    api_key=VALUES(api_key),model=VALUES(model),temperature=VALUES(temperature),
    max_tokens=VALUES(max_tokens),top_p=VALUES(top_p),is_active=VALUES(is_active),update_time=NOW();
"@)
}

$sql.Add("COMMIT;")
$sqlText = $sql -join "`n"
$previousMysqlPwd = $env:MYSQL_PWD
$previousOutputEncoding = $OutputEncoding
$env:MYSQL_PWD = $MysqlPassword
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

try {
    $sqlText | & $mysqlExe -h $MysqlHost -P $MysqlPort -u $MysqlUser --default-character-set=utf8mb4 $MysqlDatabase
    if ($LASTEXITCODE -ne 0) { throw "MySQL 迁移失败，退出码 $LASTEXITCODE" }
} finally {
    $OutputEncoding = $previousOutputEncoding
    if ($null -eq $previousMysqlPwd) {
        Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
    } else {
        $env:MYSQL_PWD = $previousMysqlPwd
    }
}

Write-Host "[OK] 已迁移数据库配置 $($databases.Count) 条、数据集 $($datasets.Count) 条、大模型配置 $($llmConfigs.Count) 条。" -ForegroundColor Green
