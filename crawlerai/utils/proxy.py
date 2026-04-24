import random

class ProxyManager:
    """
    Quản lý danh sách Proxy và xoay vòng để tránh bị block IP.
    """
    def __init__(self, proxy_list: list[str] = None):
        self.proxies = proxy_list or []

    def get_random_proxy(self):
        """Lấy một proxy ngẫu nhiên từ danh sách."""
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        # Format mong đợi: protocol://user:pass@host:port
        return {
            "server": proxy
        }

    def add_proxy(self, proxy_url: str):
        if proxy_url not in self.proxies:
            self.proxies.append(proxy_url)
