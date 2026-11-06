"""TinyAgent：消息的发出方。

传输层从 `default_bus()` 取，Agent 自己不认识 `MessageBus`——这条边界就是 v2 能把
总线换成 `Router` 而调用方一行不改的原因。
"""

from tiny.bus import MessageBus


def default_bus() -> MessageBus:
    return MessageBus()


class TinyAgent:
    def __init__(self, name: str, bus: MessageBus | None = None) -> None:
        self.name = name
        self.bus = bus or default_bus()

    def send(self, text: str) -> int:
        return self.bus.publish(self.name, text)
