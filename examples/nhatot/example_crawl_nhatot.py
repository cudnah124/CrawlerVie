import asyncio
import os
import sys

project_root = os.path.abspath('crawlerAI')
if project_root not in sys.path:
    sys.path.append(project_root)

from crawlerai.sites.nhatot import AsyncNhaTotCrawler

async def main():
    # Cấu hình tham số 
    URL = "https://www.nhatot.com/mua-ban-bat-dong-san-tp-ho-chi-minh"
    FILE_NAME = "nhatot_full_data.csv"
    LIMIT = 500
    BATCH = 10
    MAX_PAGES = 30
    # -------------------------------

    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser_profile", "nhatot_master")
    
    async with AsyncNhaTotCrawler(headless=True, user_data_dir=profile_dir) as crawler:
        await crawler.crawl_to_csv(
            list_url=URL, 
            output_file=FILE_NAME, 
            limit=LIMIT, 
            batch_size=BATCH, 
            max_pages=MAX_PAGES
        )

if __name__ == "__main__":
    asyncio.run(main())
