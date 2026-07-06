package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "ass_driver")
public class Driver {

    @Id
    @Column(length = 32)
    private String id;

    @Column(length = 100, nullable = false)
    private String name;

    @Column(name = "driver_class", length = 200)
    private String driverClass;

    @Column(name = "url_template", length = 500)
    private String urlTemplate;

    @Column(name = "jar_file_name", length = 200)
    private String jarFileName;

    @Column(name = "jar_file_path", length = 500)
    private String jarFilePath;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "update_time")
    private LocalDateTime updateTime;

    @PrePersist
    protected void onCreate() {
        createTime = LocalDateTime.now();
        updateTime = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    public Driver() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDriverClass() { return driverClass; }
    public void setDriverClass(String driverClass) { this.driverClass = driverClass; }
    public String getUrlTemplate() { return urlTemplate; }
    public void setUrlTemplate(String urlTemplate) { this.urlTemplate = urlTemplate; }
    public String getJarFileName() { return jarFileName; }
    public void setJarFileName(String jarFileName) { this.jarFileName = jarFileName; }
    public String getJarFilePath() { return jarFilePath; }
    public void setJarFilePath(String jarFilePath) { this.jarFilePath = jarFilePath; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
