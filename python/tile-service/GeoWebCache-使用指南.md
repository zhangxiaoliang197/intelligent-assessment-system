# GeoWebCache 瓦片地图服务调用指南

## 服务基本信息

| 项目 | 值 |
|------|-----|
| 服务地址 | `http://localhost:9090/geowebcache/gwc` |
| WMTS 能力文档 | `http://localhost:9090/geowebcache/gwc/service/wmts?REQUEST=GetCapabilities` |
| TMS 能力文档 | `http://localhost:9090/geowebcache/gwc/service/tms/1.0.0` |
| 瓦片格式 | PNG、JPEG |
| 瓦片大小 | 256 x 256 |
| 支持坐标系 | EPSG:4326 (WGS84)、EPSG:900913 (Web Mercator) |

## 可用图层（共 30 个）

### 中国行政图（正式地图风格）

| 图层标识符 | 名称 | 说明 |
|-----------|------|------|
| `china:china_provinces_3857` | 省级行政边界 | 35 省，浅米色填充 + 棕灰色边界线 + 中文标签 |
| `china:china_cities_3857` | 城市/区县边界 | 475 市/区县，浅米色半透明 + 边界线 + 中文标签 |
| `china:china_osm_roads_3857` | 道路网络 | 高速(黄)、国道(白)、省道(浅灰)、县道、街道(OSM 数据，当前已下载 18 省) |
| `china:china_osm_waterways_3857` | 河流水系 | 河流(浅蓝)、运河、溪流(OSM 数据) |
| `china:china_osm_waterareas_3857` | 湖泊水库 | 水域面(浅蓝)(OSM 数据) |
| `china:china_osm_railways_3857` | 铁路地铁 | 铁路(黑色虚线)、地铁(蓝色虚线)(OSM 数据) |

> **当前数据覆盖**: OSM 道路/水系/铁路数据已下载安徽、北京、上海三省。其他省份需继续下载 Geofabrik GeoPackage 数据并导入。完整的 34 省下载脚本: `download_osm_china.py`。

### 默认图层

| 图层标识符 | 名称 |
|-----------|------|
| `ne:world` | World Map |
| `ne:countries` | Countries |
| `ne:coastlines` | Coastlines |
| `ne:populated_places` | Populated Places |
| `ne:boundary_lines` | Boundary Lines |
| `ne:disputed_areas` | Disputed Areas |
| `topp:states` | USA Population |
| `tiger:tiger_roads` | Manhattan (NY) roads |
| `tiger:poly_landmarks` | Manhattan (NY) landmarks |
| `tiger:poi` | Manhattan (NY) points of interest |
| `tiger:giant_polygon` | World rectangle |
| `sf:sfdem` | Spearfish elevation |
| `sf:streams` | Spearfish streams |
| `sf:roads` | Spearfish roads |
| `sf:bugsites` | Spearfish bug locations |
| `sf:archsites` | Spearfish archeological sites |
| `sf:restricted` | Spearfish restricted areas |
| `topp:tasmania_state_boundaries` | Tasmania state boundaries |
| `topp:tasmania_cities` | Tasmania cities |
| `topp:tasmania_roads` | Tasmania roads |
| `topp:tasmania_water_bodies` | Tasmania water bodies |
| `nurc:Pk50095` | Pk50095 |
| `nurc:mosaic` | mosaic |
| `nurc:Img_Sample` | North America sample imagery |
| `nurc:Arc_Sample` | A sample ArcGrid file |
| `spearfish` | Spearfish |
| `tasmania` | Tasmania |
| `tiger-ny` | TIGER New York |

---

## 调用方式一：WMTS（推荐）

### KVP 方式（Key-Value Pair）

```
http://localhost:9090/geowebcache/gwc/service/wmts?
  layer=ne:world
  &style=
  &tilematrixset=EPSG:900913
  &Service=WMTS
  &Request=GetTile
  &Version=1.0.0
  &Format=image/png
  &TileMatrix=EPSG:900913:5
  &TileCol=16
  &TileRow=10
```

### RESTful 方式

```
http://localhost:9090/geowebcache/gwc/service/wmts/rest/ne:world/default/EPSG:900913/EPSG:900913:5/16/10?format=image/png
```

---

## 调用方式二：TMS

```
http://localhost:9090/geowebcache/gwc/service/tms/1.0.0/ne:world@EPSG:900913@png/5/16/10
```

---

## 调用方式三：WMS-C（兼容普通 WMS 客户端）

```
http://localhost:9090/geowebcache/gwc/service/wms?
  SERVICE=WMS
  &VERSION=1.1.1
  &REQUEST=GetMap
  &LAYERS=ne:world
  &STYLES=
  &FORMAT=image/png
  &SRS=EPSG:900913
  &BBOX=-20037508.34,-20037508.34,20037508.34,20037508.34
  &WIDTH=256
  &HEIGHT=256
  &tiled=true
```

**注意**：必须添加 `tiled=true` 参数，GeoWebCache 才会返回瓦片缓存。

---

## 前端项目修改指南

> **重要区分**：GeoWebCache 发布的是**行政边界图**（只有省/市/区县的多边形边界和名称），**不包含道路、建筑、POI 等街道要素**。要达到高德/百度地图那样的街道级显示效果，必须将行政边界作为**半透明覆盖层**叠加在街道底图之上。

### 方案：底图 + 行政边界叠加

| 层级 | 数据源 | 作用 |
|------|--------|------|
| 底层 | 高德/百度/OSM 街道瓦片 | 提供道路、建筑、POI、地铁等街道要素 |
| 上层 | GeoWebCache TMS 行政边界 | 叠加省/市/区县边界，半透明不遮挡底图 |

### 前端项目需要修改的内容

1. **添加街道底图图层**：在现有 GeoWebCache 图层下方添加高德/百度/OSM 瓦片作为底图。
2. **调整 GWC 图层为覆盖层**：将 GeoWebCache 行政边界图层的 `opacity` 设为 `0.3~0.5`，使其作为半透明覆盖层。
3. **设置 `tms: true`**：使用 TMS 格式调用 GeoWebCache 时，Leaflet 必须设置 `tms: true`（TMS 的 Y 轴方向与 Google/Leaflet 相反）。
4. **双图层叠加**：同时使用**省级边界**（低缩放）和**城市边界**（高缩放）两个图层。
5. **缩放响应透明度**：根据缩放级别动态调整两个行政边界图层的透明度，避免在高缩放时遮挡街道细节。
6. **移除旧图层引用**：如果旧代码引用了不再使用的图层，替换为新的 `china:china_provinces_3857` 或 `china:china_cities_3857`。

### 缩放级别策略

| 缩放级别 | 显示内容 | 省级边界透明度 | 城市边界透明度 |
|---------|---------|-------------|-------------|
| z=3~6 | 全国/大区概览 | 0.5 | 0.3 |
| z=7~9 | 省级边界清晰 | 0.4 | 0.5 |
| z=10~12 | 地级市/区县边界 | 0.15 | 0.5 |
| z=13~18 | 街道级（区县细分） | 0.1 | 0.4 |

### 中国行政图 TMS 瓦片 URL

```
# 省级行政边界（35 省多色）
http://localhost:9090/geowebcache/gwc/service/tms/1.0.0/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png

# 城市级行政边界（475 市/区县多色）
http://localhost:9090/geowebcache/gwc/service/tms/1.0.0/china:china_cities_3857@EPSG:900913@png/{z}/{x}/{y}.png
```

**注意**：`EPSG:900913` 是 GeoWebCache 内部对 Web Mercator 的命名，与 EPSG:3857 等价但瓦片 URL 中必须使用 `EPSG:900913`。

---

## 前端集成示例

### Leaflet - 内网正式行政地图（推荐方案）

```javascript
// 不需要任何互联网底图, 纯 GeoWebCache 服务
var GWC = '/geowebcache/gwc/service/tms/1.0.0';
// 直接访问(不通过代理): 'http://localhost:9090/geowebcache/gwc/service/tms/1.0.0'
var tmsOpts = { tms: true, maxZoom: 18, minZoom: 3 };

var map = L.map('map', {
    center: [31.23, 121.47],  // 上海
    zoom: 12,
    layers: [
        // 1. 省级边界 (浅米色底)
        L.tileLayer(GWC + '/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.9 })),
        // 2. 城市/区县边界
        L.tileLayer(GWC + '/china:china_cities_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.5 })),
        // 3. 湖泊水库
        L.tileLayer(GWC + '/china:china_osm_waterareas_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.8 })),
        // 4. 河流水系
        L.tileLayer(GWC + '/china:china_osm_waterways_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.7 })),
        // 5. 道路网络 (高速黄、国道白、省道灰)
        L.tileLayer(GWC + '/china:china_osm_roads_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.9 })),
        // 6. 铁路/地铁
        L.tileLayer(GWC + '/china:china_osm_railways_3857@EPSG:900913@png/{z}/{x}/{y}.png',
            Object.assign({}, tmsOpts, { opacity: 0.7 })),
    ]
});

// 缩放自适应透明度
map.on('zoomend', function() {
    var z = map.getZoom();
    // 低缩放突出省界, 高缩放突出道路
    // ...根据需要调整各图层 opacity...
});
```

### Leaflet - 基础调用方式（旧示例保留）

```javascript
// WMTS 方式
var wmtsUrl = 'http://localhost:9090/geowebcache/gwc/service/wmts?' +
    'layer=ne:world' +
    '&style=' +
    '&tilematrixset=EPSG:900913' +
    '&Service=WMTS' +
    '&Request=GetTile' +
    '&Version=1.0.0' +
    '&Format=image/png' +
    '&TileMatrix=EPSG:900913:{z}' +
    '&TileCol={x}' +
    '&TileRow={y}';

L.tileLayer(wmtsUrl, {
    maxZoom: 18,
    attribution: 'GeoWebCache'
}).addTo(map);

// TMS 方式（更简单）
var tmsUrl = 'http://localhost:9090/geowebcache/gwc/service/tms/1.0.0/' +
    'ne:world@EPSG:900913@png/{z}/{x}/{y}.png';

L.tileLayer(tmsUrl, {
    maxZoom: 18,
    tms: true,  // TMS 的 Y 轴方向与 Google/Leaflet 相反
    attribution: 'GeoWebCache'
}).addTo(map);

// WMS 方式
var wmsUrl = 'http://localhost:9090/geowebcache/gwc/service/wms';
L.tileLayer.wms(wmsUrl, {
    layers: 'ne:world',
    format: 'image/png',
    transparent: true,
    tiled: true,
    attribution: 'GeoWebCache'
}).addTo(map);
```

### OpenLayers

```javascript
import TileLayer from 'ol/layer/Tile';
import WMTS from 'ol/source/WMTS';
import WMTSTileGrid from 'ol/tilegrid/WMTS';
import {get as getProjection} from 'ol/proj';
import {getTopLeft, getWidth} from 'ol/extent';

const projection = getProjection('EPSG:900913');
const projectionExtent = projection.getExtent();
const size = getWidth(projectionExtent) / 256;
const resolutions = [];
const matrixIds = [];
for (let z = 0; z < 22; ++z) {
    resolutions[size / Math.pow(2, z)];
    matrixIds.push('EPSG:900913:' + z);
}

const wmtsLayer = new TileLayer({
    source: new WMTS({
        url: 'http://localhost:9090/geowebcache/gwc/service/wmts',
        layer: 'ne:world',
        matrixSet: 'EPSG:900913',
        format: 'image/png',
        projection: projection,
        tileGrid: new WMTSTileGrid({
            origin: getTopLeft(projectionExtent),
            resolutions: resolutions,
            matrixIds: matrixIds,
        }),
        style: '',
        wrapX: true,
    }),
});
```

### Cesium

```javascript
var viewer = new Cesium.Viewer('cesiumContainer');

viewer.imageryLayers.addImageryProvider(
    new Cesium.WebMapTileServiceImageryProvider({
        url: 'http://localhost:9090/geowebcache/gwc/service/wmts',
        layer: 'ne:world',
        style: 'default',
        format: 'image/png',
        tileMatrixSetID: 'EPSG:900913',
        tileMatrixLabels: Array.from({length: 22}, (_, i) => 'EPSG:900913:' + i),
        maximumLevel: 18,
    })
);
```

---

## Python 后端调用示例

### 使用 requests 获取单张瓦片

```python
import requests

# WMTS RESTful 方式获取瓦片
url = (
    "http://localhost:9090/geowebcache/gwc/service/wmts/rest/"
    "ne:world/default/EPSG:900913/EPSG:900913:5/16/10"
    "?format=image/png"
)

response = requests.get(url)
if response.status_code == 200:
    with open("tile.png", "wb") as f:
        f.write(response.content)
    print("瓦片下载成功")
else:
    print(f"请求失败: {response.status_code}")
```

### 批量下载瓦片

```python
import requests
import os

base_url = (
    "http://localhost:9090/geowebcache/gwc/service/wmts/rest/"
    "ne:world/default/EPSG:900913/EPSG:900913:{z}/{x}/{y}"
    "?format=image/png"
)

os.makedirs("tiles", exist_ok=True)

# 下载 zoom=5 级别的部分瓦片
for x in range(15, 18):
    for y in range(9, 12):
        url = base_url.format(z=5, x=x, y=y)
        response = requests.get(url)
        if response.status_code == 200:
            filename = f"tiles/{x}_{y}.png"
            with open(filename, "wb") as f:
                f.write(response.content)
            print(f"下载成功: {filename}")
```

---

## 缓存预热（Seeding）

通过 GeoWebCache 的 REST API 可以预先生成瓦片缓存，避免首次访问时的延迟。

### 触发 Seed 任务

```bash
# 使用 curl 触发 seed 任务
curl -v -u admin:geoserver \
  -XPOST \
  -H "Content-type: text/xml" \
  -d "<seedRequest><name>ne:world</name><srs><number>900913</number></srs><zoomStart>0</zoomStart><zoomStop>5</zoomStop><format>image/png</format><type>seed</type><threadCount>2</threadCount></seedRequest>" \
  "http://localhost:9090/geowebcache/gwc/rest/seed/ne:world.xml"
```

或通过 GeoWebCache 的 Web 管理界面操作：http://localhost:9090/geowebcache/gwc/demo 点击每个图层旁的 "Seed this layer" 按钮。

---

## 常见问题

### 中国行政图相关问题

| 问题 | 解决方案 |
|------|----------|
| 为什么只有边界没有道路？ | GeoWebCache 发布的是**行政边界图**（多边形边界+名称），不是街道底图。需要叠加高德/百度/OSM 街道瓦片作为底图。 |
| 瓦片颜色不对或只有单色 | 检查 SLD 样式是否正确加载。省级图层的样式名为 `china:china_provinces_style`，城市图层为 `china:china_cities_style`。 |
| 标签（中文地名）不显示 | 低缩放级别（z < 4）瓦片尺寸有限，标签可能太小。高缩放级别（z >= 6）标签会逐渐清晰。 |
| 城市边界图层加载空白 | 确保城市图层 `china:china_cities_3857` 已发布且 GWC 缓存已生成。城市边界在高缩放级别（z >= 8）才会清晰显示。 |
| 如何达到街道级显示？ | 行政边界图最多显示到**区县级**边界（如北京东城区、西城区）。若需要道路/POI，必须叠加第三方街道底图。 |

### 通用问题

| 问题 | 解决方案 |
|------|----------|
| 瓦片返回 404 | 检查图层名称是否正确（区分大小写），确认图层已发布。TMS URL 中注意 `EPSG:900913` 不是 `EPSG:3857`。 |
| 瓦片上下翻转 | Leaflet 中使用 TMS 格式必须设置 `tms: true`。OpenLayers 需要自定义 `tileUrlFunction` 翻转 Y 坐标。 |
| 瓦片模糊或变形 | 确认使用的坐标系（EPSG:4326 或 EPSG:900913）与前端地图一致 |
| 首次加载慢 | 使用 Seed 功能预先生成缓存瓦片 |
| 跨域问题 | 在 GeoServer 中启用 CORS，或在请求头中添加跨域配置 |
| 瓦片拼接有缝隙 | 确认瓦片大小为 256x256，检查坐标系对齐 |

### 前端修改检查清单

将以下清单用于核对你的前端项目修改是否完整：

- [ ] 已添加街道底图（高德/百度/OSM）作为最底层
- [ ] GeoWebCache 行政边界图层的 `opacity` 已调整为 `0.3~0.5`
- [ ] TMS 调用已设置 `tms: true`（Leaflet）或处理了 Y 轴翻转
- [ ] 同时使用省级边界和城市边界两个图层
- [ ] 已添加 `zoomend` 事件监听，根据缩放级别调整透明度
- [ ] 旧图层引用已替换为 `china:china_provinces_3857` 或 `china:china_cities_3857`
- [ ] 瓦片 URL 中使用 `EPSG:900913` 而非 `EPSG:3857`
- [ ] 地图中心点和缩放范围已调整为适合中国区域

---

## Vue/React 项目集成排障指南

### 常见问题：瓦片加载不出来（地图空白）

**症状**：地图底图正常或为空白，行政边界瓦片不显示，浏览器 DevTools Network 中瓦片请求返回 404 或 HTML 页面。

**原因**：前端使用了相对路径（如 `/geowebcache/gwc/...`），但没有配置开发服务器代理将请求转发到 `http://localhost:9090`。

**排查步骤**：
1. 打开浏览器 DevTools -> Network 面板
2. 筛选 `PNG` 类型的请求
3. 检查瓦片请求的 URL 和响应状态码
   - 如果返回 404：URL 路径有问题或代理未配置
   - 如果返回 200 但很小（< 100 字节）：可能是错误页面的内容而非 PNG
   - 如果完全没有请求：图层未正确添加到地图

### 解决方案 1：配置开发服务器代理

**Vite 项目**（`vite.config.ts`）：
```typescript
export default defineConfig({
  server: {
    proxy: {
      '/geowebcache': {
        target: 'http://localhost:9090',
        changeOrigin: true,
      },
    },
  },
})
```

**Vue CLI 项目**（`vue.config.js`）：
```javascript
module.exports = {
  devServer: {
    proxy: {
      '/geowebcache': {
        target: 'http://localhost:9090',
        changeOrigin: true,
      },
    },
  },
}
```

**Nginx 生产环境**：
```nginx
location /geowebcache/ {
    proxy_pass http://localhost:9090/geowebcache/;
    proxy_set_header Host $host;
}
```

### 解决方案 2：直接使用完整 URL（需开启 CORS）

在 GeoServer 中开启 CORS：
1. 登录 GeoServer Web UI -> `http://localhost:9090/geowebcache/web/`
2. 进入 `Global` -> `Settings`
3. 找到 `CORS` 设置，勾选 `Enable CORS`
4. 保存并重启服务

然后在前端直接使用完整地址：
```javascript
L.tileLayer(
  'http://localhost:9090/geowebcache/gwc/service/tms/1.0.0/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png',
  { tms: true, maxZoom: 18, opacity: 0.4 }
)
```

### 解决方案 3：TMS URL 中的冒号编码

GeoWebCache TMS URL 中的冒号 `:` 在某些代理/服务器环境下可能需要编码为 `%3A`：

```
# 原始（冒号未编码）
/geowebcache/gwc/service/tms/1.0.0/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png

# 编码后（推荐）
/geowebcache/gwc/service/tms/1.0.0/china%3Achina_provinces_3857@EPSG%3A900913@png/{z}/{x}/{y}.png
```

> **建议**：Leaflet 会自动编码 URL 模板中的特殊字符，但如果使用 axios/fetch 手动请求瓦片，需要自行编码。

### 底图方案选择

| 底图 | URL 模板 | 是否需要代理 |
|------|----------|------------|
| 高德街道（推荐） | `https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}` | 不需要（公网直连） |
| 高德卫星 | `https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}` | 不需要 |
| OpenStreetMap | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` | 不需要 |
| 本地代理高德 | `/tiles/{z}/{y}/{x}.png` | **需要**（代理到高德） |
| 天地图 | `https://t{s}.tianditu.gov.cn/vec_w/wmts?...` | 不需要（需申请 Key） |

> **建议**：优先使用公网直连的高德/OSM URL，避免配置额外的底图代理。`subdomains` 参数设为 `['1','2','3','4']` 实现负载均衡。

### Vue 组件集成模板（GeoMap.vue 关键代码）

```javascript
// 底图：直接使用高德公网 URL（无需代理）
const baseLayer = L.tileLayer(
  'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
  {
    subdomains: ['1', '2', '3', '4'],
    maxZoom: 18,
    minZoom: 3,
  }
).addTo(map)

// 省级边界：通过代理访问 GeoWebCache
const provincesLayer = L.tileLayer(
  '/geowebcache/gwc/service/tms/1.0.0/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png',
  {
    tms: true,
    maxZoom: 18,
    minZoom: 3,
    opacity: 0.4,
  }
).addTo(map)

// 城市边界：通过代理访问 GeoWebCache
const citiesLayer = L.tileLayer(
  '/geowebcache/gwc/service/tms/1.0.0/china:china_cities_3857@EPSG:900913@png/{z}/{x}/{y}.png',
  {
    tms: true,
    maxZoom: 18,
    minZoom: 3,
    opacity: 0.5,
  }
).addTo(map)

// 动态透明度
map.on('zoomend', () => {
  const z = map.getZoom()
  if (z >= 10) {
    provincesLayer.setOpacity(0.15)
    citiesLayer.setOpacity(0.45)
  } else if (z >= 7) {
    provincesLayer.setOpacity(0.3)
    citiesLayer.setOpacity(0.5)
  } else {
    provincesLayer.setOpacity(0.5)
    citiesLayer.setOpacity(0.3)
  }
})
```
