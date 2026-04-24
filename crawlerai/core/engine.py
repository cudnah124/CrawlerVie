import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from crawlerai.utils.antibot import AntiBotManager

class BaseAsyncCrawler:
    """
    Lớp cơ sở quản lý vòng đời trình duyệt Playwright.
    Mọi Site-specific Crawler sẽ kế thừa từ đây.
    """
    def __init__(self, headless=True, user_data_dir=None, timeout=60000):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.timeout = timeout
        
        self._pw = None
        self._browser = None
        self._context = None
        self.ready = False

    async def start(self):
        """Khởi động engine trình duyệt."""
        if self.ready:
            return self
            
        self._pw = await async_playwright().start()
        
        if self.user_data_dir:
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                bypass_csp=True,
                ignore_https_errors=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu"
                ]
            )
        else:
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context()
            
        self.ready = True
        return self

    async def close(self):
        """Giải phóng tài nguyên hệ thống."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self.ready = False

    async def restart_session(self):
        """Khởi chạy lại trình duyệt với profile sạch thông qua AntiBotManager."""
        await self.close()
        await AntiBotManager.clean_profile(self.user_data_dir)
        await self.start()

    async def get_new_page(self) -> Page:
        """Tạo page mới và áp dụng Stealth ngay lập tức."""
        if not self.ready:
            await self.start()
        page = await self._context.new_page()
        await AntiBotManager.apply_stealth(page)
        return page

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
