import os
import shutil
import asyncio
import random
import re
from datetime import datetime, timedelta

class AntiBotManager:
    """
    Module dùng chung chứa các kỹ thuật chống chặn, giả lập người dùng
    và quản lý phiên làm việc cho Playwright.
    """
    
    @staticmethod
    async def apply_stealth(page):
        """Áp dụng stealth để ẩn danh các đặc tính của bot."""
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            # Nếu chưa cài playwright-stealth thì bỏ qua
            pass

    @staticmethod
    async def clean_profile(profile_dir: str):
        """Xóa sạch thư mục profile để đảm bảo phiên làm việc 'sạch'."""
        if not profile_dir:
            return
        if os.path.exists(profile_dir):
            for _ in range(3):
                try:
                    shutil.rmtree(profile_dir)
                    break
                except:
                    await asyncio.sleep(1)

    @staticmethod
    async def human_like_scroll(page):
        """Cuộn trang ngẫu nhiên để kích hoạt lazy loading và giả lập người dùng."""
        steps = random.randint(2, 4)
        for i in range(steps):
            amount = random.randint(500, 900)
            await page.evaluate(f"window.scrollBy(0, {amount})")
            await asyncio.sleep(random.uniform(1.0, 2.0))

    @staticmethod
    def parse_vn_time(time_str: str | None) -> datetime | None:
        """Helper dùng chung để xử lý thời gian tiếng Việt (nếu cần)."""
        if not time_str:
            return None
        time_str = time_str.lower()
        now = datetime.now()
        if 'vừa xong' in time_str:
            return now
        match = re.search(r'(\d+)\s+phút\s+trước', time_str)
        if match:
            return now - timedelta(minutes=int(match.group(1)))
        match = re.search(r'(\d+)\s+giờ\s+trước', time_str)
        if match:
            return now - timedelta(hours=int(match.group(1)))
        if 'hôm qua' in time_str:
            return now - timedelta(days=1)
        match = re.search(r'(\d+)\s+ngày\s+trước', time_str)
        if match:
            return now - timedelta(days=int(match.group(1)))
        return None

    @staticmethod
    def clean_emojis(text: str | None) -> str:
        """Xóa icon/emoji gây nhiễu dữ liệu."""
        if not text:
            return ""
        emoji_pattern = re.compile(
            "["
            "\U00010000-\U0010FFFF"
            "\u2600-\u27BF"
            "\u2300-\u23FF"
            "]+", flags=re.UNICODE)
        return emoji_pattern.sub(r'', text).strip()
