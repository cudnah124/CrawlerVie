import os
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse

class MediaDownloader:
    """
    Utility để tải ảnh/video bất đồng bộ.
    """
    
    @staticmethod
    async def download_file(session: aiohttp.ClientSession, url: str, save_path: str) -> bool:
        """Tải một file duy nhất."""
        try:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    f = await aiofiles.open(save_path, mode='wb')
                    await f.write(await response.read())
                    await f.close()
                    return True
                else:
                    print(f"    [Downloader] Failed: {url} (Status: {response.status})")
                    return False
        except Exception as e:
            print(f"    [Downloader] Error: {url} - {e}")
            return False

    @staticmethod
    async def download_batch(urls: list[str], output_dir: str, concurrency: int = 5) -> list[str]:
        """
        Tải một loạt file vào thư mục đích.
        Trả về danh sách các file đã tải thành công (đường dẫn local).
        """
        if not urls:
            return []
            
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        downloaded_paths = []
        sem = asyncio.Semaphore(concurrency)
        
        async with aiohttp.ClientSession() as session:
            async def _bounded_download(url):
                async with sem:
                    # Lấy tên file từ URL hoặc hash nếu cần
                    filename = os.path.basename(urlparse(url).path)
                    if not filename or "." not in filename:
                        filename = f"img_{hash(url)}.jpg"
                    
                    save_path = os.path.join(output_dir, filename)
                    
                    # Nếu file đã tồn tại thì bỏ qua (hoặc có thể thêm logic check size/hash)
                    if os.path.exists(save_path):
                        return save_path
                        
                    success = await MediaDownloader.download_file(session, url, save_path)
                    return save_path if success else None

            tasks = [_bounded_download(url) for url in urls]
            results = await asyncio.gather(*tasks)
            downloaded_paths = [r for r in results if r]
            
        return downloaded_paths
