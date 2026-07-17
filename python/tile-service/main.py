import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="Tile Service", description="内网瓦片地图服务", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TILE_DIR = os.path.join(os.path.dirname(__file__), "tiles")
os.makedirs(TILE_DIR, exist_ok=True)

MIN_ZOOM = 0
MAX_ZOOM = 18

TILE_SOURCES = [
    {
        "name": "autonavi",
        "url": "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"],
    },
    {
        "name": "arcgis",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "subdomains": ["0"],
    },
    {
        "name": "gaode",
        "url": "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"],
    },
]

async def get_external_tile_from_source(source: dict, z: int, y: int, x: int) -> bytes:
    subdomain = source["subdomains"][z % len(source["subdomains"])]
    url = source["url"].format(s=subdomain, z=z, y=y, x=x)
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=15)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="瓦片不存在")
        response.raise_for_status()
        return response.content

async def get_external_tile(z: int, y: int, x: int) -> bytes:
    last_error = None
    for source in TILE_SOURCES:
        try:
            data = await get_external_tile_from_source(source, z, y, x)
            if b"Map data not yet available" in data:
                continue
            return data
        except Exception as e:
            last_error = e
            continue
    raise HTTPException(status_code=404, detail=f"所有瓦片源都不可用: {str(last_error)}")

def get_tile_path(z: int, y: int, x: int) -> str:
    tile_path = os.path.join(TILE_DIR, str(z), str(y), f"{x}.png")
    return tile_path

async def get_tile_with_fallback(z: int, y: int, x: int) -> bytes:
    tile_path = get_tile_path(z, y, x)
    if os.path.exists(tile_path):
        with open(tile_path, "rb") as f:
            return f.read()

    try:
        data = await get_external_tile(z, y, x)
        tile_dir = os.path.dirname(tile_path)
        os.makedirs(tile_dir, exist_ok=True)
        with open(tile_path, "wb") as f:
            f.write(data)
        return data
    except HTTPException as e:
        if e.status_code == 404 and z > MIN_ZOOM:
            parent_z = z - 1
            parent_x = x // 2
            parent_y = y // 2
            return await get_tile_with_fallback(parent_z, parent_y, parent_x)
        raise

@app.get("/tiles/{z}/{y}/{x}.png")
async def get_tile(z: int, y: int, x: int):
    if z < MIN_ZOOM:
        z = MIN_ZOOM
    if z > MAX_ZOOM:
        z = MAX_ZOOM

    try:
        tile_data = await get_tile_with_fallback(z, y, x)
        return Response(content=tile_data, media_type="image/png")
    except HTTPException as e:
        raise HTTPException(status_code=500, detail=f"获取瓦片失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")

@app.get("/health")
async def health():
    return {"status": "ok", "tile_count": count_tiles()}

def count_tiles() -> int:
    count = 0
    for root, dirs, files in os.walk(TILE_DIR):
        for f in files:
            if f.endswith(".png"):
                count += 1
    return count

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("TILE_SERVICE_PORT", 9090))
    uvicorn.run(app, host="0.0.0.0", port=port)
