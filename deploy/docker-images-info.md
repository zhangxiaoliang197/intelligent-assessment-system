# Docker Desktop 镜像构建信息

## 2026-07-23 QA Skill 目录修复包

`assessment-qa:latest` 已在 2026-07-23 重新构建并通过镜像内目录校验、
63 项后端测试和真实容器 HTTP 冒烟测试。部署时应以本节版本为准，
并强制重建容器，不能使用 `docker compose restart`。

- Image ID：`sha256:3334817f0bc2f3723415af468cf8bfb06d43d04f8adfae847b5e99203a2097ee`
- `assessment-qa.tar`：79,555,072 B
- SHA256：`7E8184D1C2C81172DAAA738985B1EF2891FE95DC5FE241177E6CC8C8D212F9F2`
- 健康检查：`/health` 返回 `skillCount=15`
- 目录接口：`/evaluation/skills` 返回 `builtInTotal=15`
- 一键包：`assessment-qa-skill-hotfix-20260723.tar.gz`（79,025,405 B）
- 一键包 SHA256：`AB85D5D4A31F2884DE04C56EC035F6839958F92B044BC283E6DF59C2F1E9AC44`

现场只替换 QA：

```bash
tar -xzf assessment-qa-skill-hotfix-20260723.tar.gz
bash deploy/apply-qa-skill-hotfix.sh
```

## 构建概况

- 构建时间：2026-07-22 15:59:56 +08:00（Asia/Shanghai）
- 源代码分支：`main`
- 源代码提交：`839e255`（fix: 修复坐标范围解析，中心点计算错误(取到西南角而非中心)）
- Docker Desktop：4.74.0（Engine 29.4.3）
- 构建平台：`linux/amd64`
- 镜像标签：`latest`
- 构建结果：7/7 成功

## 镜像清单

| 镜像 | Image ID | 大小 | 对外端口 | 状态 |
| --- | --- | ---: | ---: | --- |
| `assessment-frontend:latest` | `sha256:cb497b523d31626f4e48223a67e3e505e6e8e00ab868500c541bbc8217037a30` | 17,866,256 B（约 17.04 MiB） | 10086 | 构建成功 |
| `assessment-knowledge:latest` | `sha256:0efccb39989f28a9166f3fd9e8aa005418e74ae37717367a08efa54b74a7a564` | 145,014,289 B（约 138.30 MiB） | 10252 | 构建成功 |
| `assessment-qa:latest` | `sha256:4ec660b90e35ad3902d5eb9b9402dd7dd18d41705787f81bc9ec2d71aaca1a1d` | 79,414,346 B（约 75.74 MiB） | 10253 | 构建成功 |
| `assessment-indicator:latest` | `sha256:6d2fb0226f1b7ab945349b3c031f60765aea3d699fc10b03768b6f2b0e7fdf8e` | 54,737,748 B（约 52.20 MiB） | 10254 | 构建成功 |
| `assessment-evaluation:latest` | `sha256:5b1dfe1f65bd98bb52b16b005d3e03560857b0c7348acabf72abb36f4020a3e5` | 54,678,771 B（约 52.15 MiB） | 10255 | 构建成功 |
| `assessment-ontology:latest` | `sha256:61099b7b197bfb491c61c3fc5406781e906eb5c255323716adf7e610165936b1` | 54,687,889 B（约 52.15 MiB） | 10256 | 构建成功 |
| `assessment-admin:latest` | `sha256:18e6908175a986e0a7d545903dff8fcb1df8bc322774d1b633a1f8f0bda35b3c` | 482,135,435 B（约 459.80 MiB） | 10258 | 构建成功 |

## 构建依据

- 镜像名称和构建顺序参考 `deploy/build-images.sh`。
- Dockerfile 位于 `docker/Dockerfile.*`。
- 运行时镜像映射和端口参考根目录 `docker-compose.yml`。
- 前端镜像构建前已重新执行 `npm run build`，最新产物位于 `frontend/dist`。

## 构建期间的仓库调整

原部署配置使用的清华 PyPI 镜像返回了与官方 SHA256 不一致的 `scipy` 内容，并出现 SSL 中断；阿里云 Maven 镜像也无法完整解析 Surefire 依赖。为保证依赖完整性并完成可重复构建，已作以下调整：

- 5 个 Python 服务 Dockerfile 的 pip 源改为 `https://pypi.org/simple`。
- `docker/settings.xml` 的 Maven 镜像改为 `https://repo.maven.apache.org/maven2`。

## 本地使用

查看镜像：

```powershell
docker image ls
```

按项目 Compose 配置启动：

```powershell
docker compose up -d
```

## 离线镜像包

离线包位于根目录 `docker-images/`，共 7 个文件，总大小 888,670,208 B（约 847.50 MiB）。

| 文件 | 大小 | SHA256 |
| --- | ---: | --- |
| `assessment-admin.tar` | 482,158,080 B（约 459.82 MiB） | `FA0256E3B5246148F0482FD3E12B5B98A47DED142107FF4F93E12ADEC01070F7` |
| `assessment-evaluation.tar` | 54,697,472 B（约 52.16 MiB） | `5DE7C91D8424310B0DE0E306929FF6652650B999AB6D62F5D5B6AD3B65FE487C` |
| `assessment-frontend.tar` | 17,885,184 B（约 17.06 MiB） | `43B64D59E72AEEA150B095AD5728E8E0C46D903F2125B2F86BA875D3D8786CC9` |
| `assessment-indicator.tar` | 54,756,352 B（约 52.22 MiB） | `C5E8EDE217BECACD77363288319D739873A282518576C8B69B4D5EDF70CB173E` |
| `assessment-knowledge.tar` | 145,033,216 B（约 138.31 MiB） | `318B824FBA5A91A9B66507E150B36F051576708C6BF9B0B9103CAE70FD004B07` |
| `assessment-ontology.tar` | 54,706,688 B（约 52.17 MiB） | `DE72F5A616EC251075626670853B29E1FAF8CE7B5EABCDE820AD46CD16043354` |
| `assessment-qa.tar` | 79,433,216 B（约 75.75 MiB） | `5BD0891BF332CA5F3E619F391CCDD2DB050D196E415BCFBCA286240B649FEE84` |

离线环境加载单个镜像：

```bash
docker load -i docker-images/assessment-frontend.tar
```

在 Bash 环境批量加载：

```bash
for image in docker-images/*.tar; do docker load -i "$image"; done
```
