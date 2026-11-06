"""最小可跑入口：两个 agent 共用一条总线，各说一句话。"""

from tiny.agent import TinyAgent, default_bus


def main() -> list[tuple[str, str]]:
    bus = default_bus()
    alice = TinyAgent("alice", bus)
    bob = TinyAgent("bob", bus)
    alice.send("hello")
    bob.send("hi")
    return bus.log


if __name__ == "__main__":
    print(main())
