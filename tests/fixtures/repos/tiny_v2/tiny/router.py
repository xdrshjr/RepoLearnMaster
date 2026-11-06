"""Router：v2 新增的传输层，按发送者登记的处理函数做一次转发。

它自己保留 `log`，因此不再需要 `tiny/bus.py`：一个只有四个文件的小仓库里，
两份"追加日志"必然演化成两份不一致的历史。
"""

from collections.abc import Callable


class Router:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.routes: dict[str, Callable[[str], None]] = {}

    def register(self, name: str, handler: Callable[[str], None]) -> None:
        self.routes[name] = handler

    def publish(self, sender: str, text: str) -> int:
        self.log.append((sender, text))
        handler = self.routes.get(sender)
        if handler is not None:
            handler(text)
        return len(self.log)
