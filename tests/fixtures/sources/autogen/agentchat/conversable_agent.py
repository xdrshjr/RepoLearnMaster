"""ConversableAgent: 可收发消息、调用工具的 Agent 基类。"""

class ConversableAgent:
    def __init__(self, name, llm_config=None):
        self.name = name
        self.llm_config = llm_config or {}
        self.chat_messages = {}

    def send(self, message, recipient):
        self.chat_messages.setdefault(recipient.name, []).append(message)
        return recipient.receive(message, self)

    def receive(self, message, sender):
        return self.generate_reply(messages=self.chat_messages.get(sender.name, []))

    def generate_reply(self, messages=None):
        if not self.llm_config:
            return None
        return {'role': 'assistant', 'content': 'ok'}
