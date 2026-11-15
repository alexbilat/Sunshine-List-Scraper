"""The agent loop, offline: a scripted fake model and a fake database connection."""
from contextlib import nullcontext
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sunshine_scraper.agent import agent


def reply(content=None, tool_calls=()):
    """Shape one chat-completion response the way the openai SDK returns it."""
    calls = [SimpleNamespace(id=f'call_{i}', function=SimpleNamespace(name=name, arguments=args))
             for i, (name, args) in enumerate(tool_calls)]
    message = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """Returns the scripted replies in order and remembers what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model, messages, tools):
        # Copy: the loop keeps appending to the same list after this call.
        self.sent.append(list(messages))
        return self.replies.pop(0)


def connect():
    return nullcontext('fake connection')


class AgentLoopTests(unittest.TestCase):
    def test_tool_call_then_answer(self):
        client = FakeClient(reply(tool_calls=[('top_earners', '{"year": 2024}')]),
                            reply('Sam earned the most.'))
        with patch.dict(agent.FUNCTIONS,
                        {'top_earners': lambda connection, year: [{'year': year}]}):
            answer, calls = agent.run_agent('Who earned most?', [], connect, client)
        self.assertEqual(answer, 'Sam earned the most.')
        self.assertEqual(calls, [{'name': 'top_earners', 'arguments': '{"year": 2024}'}])
        # The second request carries the tool result, tied to its call id.
        tool_message = client.sent[1][-1]
        self.assertEqual(tool_message['role'], 'tool')
        self.assertEqual(tool_message['tool_call_id'], 'call_0')
        self.assertEqual(json.loads(tool_message['content']), [{'year': 2024}])

    def test_history_comes_after_system_prompt(self):
        client = FakeClient(reply('Hi.'))
        history = [{'role': 'user', 'content': 'a'}, {'role': 'assistant', 'content': 'b'}]
        agent.run_agent('c', history, connect, client)
        roles = [message['role'] for message in client.sent[0]]
        self.assertEqual(roles, ['system', 'user', 'assistant', 'user'])

    def test_tool_error_goes_back_to_model(self):
        def broken(connection, year):
            raise ValueError('year must be an integer such as 2024')

        client = FakeClient(reply(tool_calls=[('top_earners', '{"year": "x"}')]),
                            reply('Sorry.'))
        with patch.dict(agent.FUNCTIONS, {'top_earners': broken}):
            answer, _ = agent.run_agent('q', [], connect, client)
        self.assertEqual(answer, 'Sorry.')
        self.assertIn('year must be an integer', client.sent[1][-1]['content'])

    def test_unknown_tool_and_bad_json_become_errors(self):
        self.assertIn('unknown tool', agent.run_tool('drop_tables', '{}', connect))
        self.assertIn('error', agent.run_tool('top_earners', 'not json', connect))

    def test_stops_after_max_iterations(self):
        looping = [reply(tool_calls=[('top_earners', '{"year": 2024}')])] * agent.MAX_ITERATIONS
        client = FakeClient(*looping)
        with patch.dict(agent.FUNCTIONS, {'top_earners': lambda connection, year: []}):
            answer, calls = agent.run_agent('q', [], connect, client)
        self.assertEqual(answer, agent.GAVE_UP_ANSWER)
        self.assertEqual(len(calls), agent.MAX_ITERATIONS)


if __name__ == '__main__':
    unittest.main()
