"""GroupChat: 多个 Agent 按顺序轮转的群聊编排。"""

class GroupChat:
    def __init__(self, agents, max_round=10):
        self.agents = agents
        self.max_round = max_round

    def run(self, initial_message):
        message = initial_message
        for _ in range(self.max_round):
            for agent in self.agents:
                message = agent.send(message, self.agents[0])
        return message
