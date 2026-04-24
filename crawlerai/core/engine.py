from playwright.async_api import async_playwright, Page
from crawlerai.utils.antibot import AntiBotManager

# ── Stealth constants (khôi phục từ phiên bản gốc) ────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--disable-infobars",
    "--window-position=0,0",
    "--ignore-certificate-errors",
    "--ignore-certificate-errors-spki-list",
]
# Navigator override script để ẩn webdriver flag
_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined, configurable: true,
    });
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5], configurable: true,
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['vi-VN', 'vi', 'en-US', 'en'], configurable: true,
    });
    window.chrome = { runtime: {} };
"""


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
        """Khởi động engine trình duyệt với đầy đủ cấu hình stealth."""
        if self.ready:
            return self

        self._pw = await async_playwright().start()

        if self.user_data_dir:
            # Persistent context: giữ cookies, vượt CF tốt hơn
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                args=_ARGS,
                user_agent=_UA,
                viewport={"width": 1920, "height": 1080},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                bypass_csp=True,
                ignore_https_errors=True,
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                },
            )
            # Ẩn webdriver flag ở mọi page trong context
            await self._context.add_init_script(_INIT_SCRIPT)
        else:
            self._browser = await self._pw.chromium.launch(headless=self.headless, args=_ARGS)
            self._context = await self._browser.new_context(
                user_agent=_UA,
                viewport={"width": 1920, "height": 1080},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
            )
            await self._context.add_init_script(_INIT_SCRIPT)

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
        """Đóng session cũ, xóa profile, khởi động lại với danh tính mới."""
        print("[Engine] Closing session...")
        await self.close()
        print("[Engine] Cleaning profile...")
        await AntiBotManager.clean_profile(self.user_data_dir)
        print("[Engine] Starting fresh browser...")
        await self.start()
        print("[Engine] Browser ready.")

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
