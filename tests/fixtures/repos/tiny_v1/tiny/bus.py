"""进程内消息总线：只保留「谁说了什么」的追加日志。

刻意不用队列与线程：夹具里的代码要能被静态分析一眼读完，任何异步细节都会让
"这份 diff 到底改了哪一行"变成需要调试的问题。
"""


class MessageBus:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    def publish(self, sender: str, text: str) -> int:
        """追加一条消息，返回投递后的消息总数（调用方用它做最朴素的重试判断）。"""
        self.log.append((sender, text))
        return len(self.log)
