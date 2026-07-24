@echo off
set DB_TYPE=h2
cd /d "d:\code\intelligent-assessment-system\java\admin-service"
start javaw -jar target\admin-service-1.0.0.jar
echo Admin service started with H2 mode
