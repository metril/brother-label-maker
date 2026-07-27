"""Background print-job processing: the async worker (worker.py) that
dequeues and prints jobs, and the pub/sub EventBus (events.py) that
broadcasts their lifecycle to connected WebSocket clients (api/ws.py).
"""
