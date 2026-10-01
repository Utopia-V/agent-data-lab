import io
import json
from queue import Queue
from types import SimpleNamespace
import unittest

from agent_data_lab.runner import CodexRunner


class CaptureBoundary(unittest.TestCase):
    def test_followup_reuses_thread_and_counts_only_new_tokens(self):
        from pathlib import Path
        client=object.__new__(CodexRunner)
        client.cwd=Path('/tmp')
        client.model,client.effort,client.timeout='test-model','high',1
        client.errors=[]
        client.thread_usage={'existing':{'inputTokens':100,'cachedInputTokens':60,'outputTokens':10}}
        requests=[]
        def request(method,params):
            requests.append((method,params))
            return {'turn':{'id':'next'}}
        client.request=request
        events=iter([
            {'method':'thread/tokenUsage/updated','params':{'threadId':'existing','tokenUsage':{
                'total':{'inputTokens':145,'cachedInputTokens':90,'outputTokens':18},
                'last':{'inputTokens':45,'outputTokens':8}}}},
            {'method':'turn/completed','params':{'threadId':'existing','turn':{'id':'old','status':'completed'}}},
            {'method':'turn/completed','params':{'threadId':'existing','turn':{'id':'next','status':'completed'}}},
        ])
        client.receive=lambda _:next(events)
        result=client.run('followup',None,thread_id='existing')
        self.assertEqual([method for method,_ in requests],['turn/start'])
        self.assertEqual(result['turn_id'],'next')
        self.assertEqual(result['usage']['total'],{'inputTokens':45,'cachedInputTokens':30,'outputTokens':8})
        self.assertEqual(result['cumulative_usage']['total']['inputTokens'],145)

    def test_completed_exchange_is_preserved_before_a_later_turn_failure(self):
        client=object.__new__(CodexRunner)
        from pathlib import Path
        client.cwd=Path('/tmp')
        client.model,client.effort,client.timeout='test-model','high',1
        requests=iter([{"thread":{"id":"t"}},{"turn":{"id":"u"}}])
        client.request=lambda *_:next(requests)
        replies=[]
        client.send=replies.append
        events=iter([{"id":42,"method":"item/tool/call","params":{"tool":"run","arguments":{"command":"echo value"}}}])
        def receive(_):
            try: return next(events)
            except StopIteration: raise TimeoutError('injected later failure')
        client.receive=receive
        preserved=[]
        sandbox=SimpleNamespace(run=lambda **_: {"exit_code":0,"output":"value\n"})
        with self.assertRaises(TimeoutError):
            client.run('task',sandbox,on_exchange=preserved.append)
        self.assertEqual(preserved[0]['result']['output'],'value\n')
        self.assertEqual(replies[0]['id'],42)

    def test_capture_discards_reasoning_and_keeps_completion_usage_and_visible_answer(self):
        messages = [
            {"method":"rawResponseItem/completed", "params":{"item":{"type":"reasoning","content":"PRIVATE_SENTINEL"}}},
            {"method":"item/completed", "params":{"item":{"type":"reasoning","content":"PRIVATE_SENTINEL"}}},
            {"method":"rawResponse/completed", "params":{"threadId":"t","turnId":"u","responseId":"r","usage":{"inputTokens":10},"other":"PRIVATE_SENTINEL"}},
            {"method":"item/completed", "params":{"turnId":"u","item":{"type":"agentMessage","phase":"final_answer","text":"visible"}}},
            {"method":"item/completed", "params":{"turnId":"u","item":{"type":"commandExecution","aggregatedOutput":"HOST_SENTINEL"}}},
        ]
        client = object.__new__(CodexRunner)
        client.queue = Queue()
        client.proc = SimpleNamespace(stdout=io.StringIO("".join(json.dumps(x)+"\n" for x in messages)))
        client._reader()
        captured=[]
        while not client.queue.empty():
            captured.append(client.queue.get_nowait())
        serialized=json.dumps(captured)
        self.assertNotIn("PRIVATE_SENTINEL", serialized)
        self.assertNotIn("HOST_SENTINEL", serialized)
        self.assertIn("visible", serialized)
        self.assertEqual(captured[0]["params"]["usage"], {"inputTokens":10})
        self.assertEqual(captured[-1]["method"], "unexpected/tool")


if __name__ == "__main__":
    unittest.main()
