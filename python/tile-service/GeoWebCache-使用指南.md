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

## 可用图层（共 28 个）

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

## 前端集成示例

### Leaflet（推荐）

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

| 问题 | 解决方案 |
|------|----------|
| 瓦片返回 404 | 检查图层名称是否正确（区分大小写），确认图层已发布 |
| 瓦片模糊或变形 | 确认使用的坐标系（EPSG:4326 或 EPSG:900913）与前端地图一致 |
| 首次加载慢 | 使用 Seed 功能预先生成缓存瓦片 |
| 跨域问题 | 在 GeoServer 中启用 CORS，或在请求头中添加跨域配置 |
| 瓦片拼接有缝隙 | 确认瓦片大小为 256x256，检查坐标系对齐 |
