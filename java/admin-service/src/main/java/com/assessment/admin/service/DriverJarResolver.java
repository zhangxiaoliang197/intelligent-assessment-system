/*
 * 定位：admin-service 驱动加载层的基础设施服务。
 * 作用：把「数据库里记录的 JDBC 驱动 JAR 路径」解析为磁盘上真实可用的文件：
 *   1) 优先按记录路径精确查找；
 *   2) 精确路径失效时，扫描驱动存储目录下的全部 JAR，按驱动类名匹配出可用文件（通配加载）；
 *   3) 匹配成功后把可移植路径回写数据库，自愈历史部署遗留的失效路径。
 * 所有需要动态加载 JDBC 驱动的调用方（建连、元数据查询、SQL 执行）都走这里，避免各自实现不一致。
 */
package com.assessment.admin.service;

import com.assessment.admin.model.Driver;
import com.assessment.admin.repository.DriverRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.jar.JarFile;
import java.util.stream.Stream;

@Service
public class DriverJarResolver {

    private static final Logger logger = LoggerFactory.getLogger(DriverJarResolver.class);

    /** 驱动存储目录；application.yml 中默认 ${user.dir}/drivers，随工作目录迁移，禁止写死绝对路径 */
    @Value("${driver.storage-path:drivers}")
    private String driverStoragePath;

    private final DriverRepository driverRepo;

    public DriverJarResolver(DriverRepository driverRepo) {
        this.driverRepo = driverRepo;
    }

    /**
     * 驱动 JAR 的解析结果。
     *
     * @param file         磁盘上真实存在的 JAR 文件
     * @param relativePath 可回写数据库的可移植路径（相对工作目录，统一用 / 分隔）
     * @param recovered    是否由「通配匹配」恢复（true 表示原记录路径已失效）
     */
    public record ResolvedJar(File file, String relativePath, boolean recovered) {}

    /**
     * 解析并自愈：解析成功后若命中通配结果，立即把新路径写回驱动记录。
     *
     * @param driver 驱动记录（可能带有已失效的历史路径，或路径为空）
     * @return 解析结果
     * @throws IOException 精确路径与通配匹配都找不到可用 JAR
     */
    public ResolvedJar resolveAndHeal(Driver driver) throws IOException {
        ResolvedJar resolved = resolve(driver);
        if (resolved.recovered()) {
            String previous = driver.getJarFilePath();
            driver.setJarFilePath(resolved.relativePath());
            driver.setJarFileName(resolved.file().getName());
            driverRepo.save(driver);
            logger.info("驱动 {} 的JAR路径已自愈: {} -> {}",
                    driver.getName(), previous, resolved.relativePath());
        }
        return resolved;
    }

    /**
     * 只解析不写库，供启动期统一巡检等场景使用。
     *
     * @param driver 驱动记录
     * @return 解析结果
     * @throws IOException 找不到可用 JAR
     */
    public ResolvedJar resolve(Driver driver) throws IOException {
        if (driver == null) {
            throw new IOException("驱动记录为空");
        }
        String driverClass = driver.getDriverClass();
        if (driverClass == null || driverClass.isBlank()) {
            throw new IOException("驱动 '" + driver.getName() + "' 未配置驱动类");
        }

        // ── 1. 按记录路径精确查找 ──
        File exact = locateExact(driver.getJarFilePath());
        if (exact != null) {
            return new ResolvedJar(exact, toPortablePath(exact.toPath()), false);
        }

        // ── 2. 通配匹配：扫描存储目录，找真正包含该驱动类的 JAR ──
        for (File jar : listJarFiles()) {
            if (containsClass(jar, driverClass)) {
                logger.info("驱动 {} 的记录路径 {} 不可用，已通配匹配到 {}",
                        driver.getName(), driver.getJarFilePath(), jar.getName());
                return new ResolvedJar(jar, toPortablePath(jar.toPath()), true);
            }
        }

        throw new IOException("驱动 '" + driver.getName() + "' 的JAR文件不存在: "
                + driver.getJarFilePath() + "；在 " + storageDir() + " 下也未找到包含驱动类 "
                + driverClass + " 的JAR，请在「驱动管理」中重新上传");
    }

    /**
     * 按记录路径查找真实文件；相对路径以工作目录为基准，纯文件名再兜底到驱动目录。
     *
     * @param storedPath 数据库记录的 jar_file_path，可为空
     * @return 存在的文件；不存在返回 null
     */
    private File locateExact(String storedPath) {
        if (storedPath == null || storedPath.isBlank()) {
            return null;
        }
        Path stored = Paths.get(storedPath.trim());
        List<Path> candidates = new ArrayList<>();
        if (stored.isAbsolute()) {
            candidates.add(stored);
        } else {
            candidates.add(workingDir().resolve(stored));
            if (stored.getParent() == null) {
                candidates.add(storageDir().resolve(stored));
            }
        }
        for (Path candidate : candidates) {
            if (Files.isRegularFile(candidate)) {
                return candidate.toFile();
            }
        }
        return null;
    }

    /**
     * 列出驱动目录下全部 JAR；目录不存在或无权限时返回空列表，由调用方给出可读错误。
     *
     * @return 按文件名排序的 JAR 列表
     */
    private List<File> listJarFiles() {
        Path dir = storageDir();
        if (!Files.isDirectory(dir)) {
            return List.of();
        }
        try (Stream<Path> stream = Files.list(dir)) {
            return stream.filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().toLowerCase().endsWith(".jar"))
                    .sorted(Comparator.comparing(path -> path.getFileName().toString()))
                    .map(Path::toFile)
                    .toList();
        } catch (IOException e) {
            logger.warn("扫描驱动目录 {} 失败: {}", dir, e.getMessage());
            return List.of();
        }
    }

    /**
     * 判断 JAR 内是否包含指定的驱动类，避免把同名但内容不对的包加载进来。
     *
     * @param jar         JAR 文件
     * @param driverClass 驱动类全限定名
     * @return 包含该类条目返回 true
     */
    private boolean containsClass(File jar, String driverClass) {
        String entryName = driverClass.replace('.', '/') + ".class";
        try (JarFile jarFile = new JarFile(jar)) {
            return jarFile.getEntry(entryName) != null;
        } catch (IOException e) {
            logger.warn("驱动JAR {} 无法读取，已跳过: {}", jar.getName(), e.getMessage());
            return false;
        }
    }

    /**
     * 驱动存储目录绝对路径；未配置时退化为工作目录下的 drivers 目录。
     *
     * @return 规范化后的绝对路径
     */
    private Path storageDir() {
        Path dir = Paths.get(driverStoragePath);
        if (!dir.isAbsolute()) {
            dir = workingDir().resolve(dir);
        }
        return dir.normalize();
    }

    /**
     * 进程工作目录，作为所有相对路径的解析基准（本地为项目根，容器内为 /app）。
     *
     * @return 工作目录绝对路径
     */
    private Path workingDir() {
        return Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
    }

    /**
     * 把实际文件路径转成相对工作目录的可移植路径，统一使用 / 分隔，便于跨机器同步。
     *
     * @param file 实际文件路径
     * @return 可写回数据库的路径
     */
    private String toPortablePath(Path file) {
        Path absolute = file.toAbsolutePath().normalize();
        try {
            return workingDir().relativize(absolute).toString().replace(File.separatorChar, '/');
        } catch (IllegalArgumentException e) {
            // 不在工作目录下（例如自定义外部挂载目录）时保留绝对路径
            return absolute.toString().replace(File.separatorChar, '/');
        }
    }
}
