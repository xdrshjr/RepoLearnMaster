"""TinyAgent：消息的发出方。

v2 把传输层从 `MessageBus` 换成了 `Router`：构造签名与 `send()` 都没动，变的只是
`default_bus()` 造出来的对象——「改动集中在两个函数里」正是我们希望 diff 呈现的样子。
"""

from tiny.router import Router


def default_bus() -> Router:
    return Router()


class TinyAgent:
    def __init__(self, name: str, bus: Router | None = None) -> None:
        self.name = name
        self.bus = bus or default_bus()

    def send(self, text: str) -> int:
        return self.bus.publish(self.name, text)

    def received(self) -> list[tuple[str, str]]:
        """v2 新增：别人说给我听的消息（v1 里只能自己去翻 bus.log）。"""
        return [item for item in self.bus.log if item[0] != self.name]
