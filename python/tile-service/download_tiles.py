import os
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

TILE_DIR = os.path.join(os.path.dirname(__file__), "tiles")
EXTERNAL_TILE_URL = "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"

CHINA_BOUNDS = {
    "min_lng": 73.6,
    "max_lng": 135.0,
    "min_lat": 3.8,
    "max_lat": 53.6,
}

def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple:
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def num2deg(xtile: int, ytile: int, zoom: int) -> tuple:
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def get_tile_range(zoom: int) -> tuple:
    min_x, max_y = deg2num(CHINA_BOUNDS["max_lat"], CHINA_BOUNDS["min_lng"], zoom)
    max_x, min_y = deg2num(CHINA_BOUNDS["min_lat"], CHINA_BOUNDS["max_lng"], zoom)
    return (min_x, max_x, min_y, max_y)

async def download_tile(z: int, y: int, x: int, session: httpx.AsyncClient) -> bool:
    tile_path = os.path.join(TILE_DIR, str(z), str(y), f"{x}.png")
    if os.path.exists(tile_path):
        return True
    
    subdomain = str((z % 4) + 1)
    url = EXTERNAL_TILE_URL.format(s=subdomain, z=z, y=y, x=x)
    try:
        response = await session.get(url, timeout=30)
        response.raise_for_status()
        
        tile_dir = os.path.dirname(tile_path)
        os.makedirs(tile_dir, exist_ok=True)
        
        with open(tile_path, "wb") as f:
            f.write(response.content)
        
        return True
    except Exception as e:
        print(f"下载失败 z={z} y={y} x={x}: {e}")
        return False

async def download_zoom_level(zoom: int, max_concurrent: int = 30):
    min_x, max_x, min_y, max_y = get_tile_range(zoom)
    total_tiles = (max_x - min_x + 1) * (max_y - min_y + 1)
    
    print(f"\n下载 Zoom {zoom}: {min_x}-{max_x}, {min_y}-{max_y} ({total_tiles} 个瓦片)")
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def bounded_download(z, y, x, session):
        async with semaphore:
            return await download_tile(z, y, x, session)
    
    async with httpx.AsyncClient() as session:
        tasks = []
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                tasks.append(bounded_download(zoom, y, x, session))
        
        results = []
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc=f"Zoom {zoom}"):
            results.append(await f)
        
        success = sum(results)
        print(f"Zoom {zoom} 完成: {success}/{len(results)}")

async def main():
    import math
    
    os.makedirs(TILE_DIR, exist_ok=True)
    
    zoom_levels = [3, 4, 5, 6, 7, 8, 9]
    
    for zoom in zoom_levels:
        await download_zoom_level(zoom)
    
    total = 0
    for root, dirs, files in os.walk(TILE_DIR):
        for f in files:
            if f.endswith(".png"):
                total += 1
    print(f"\n总计下载 {total} 个瓦片")

if __name__ == "__main__":
    asyncio.run(main())
