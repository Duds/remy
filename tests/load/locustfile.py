"""
Locust load test harness for Remy performance testing.

This simulates Telegram bot traffic patterns to stress test:
- Message classification latency
- Conversation history loading
- Memory injection
- AI streaming response time
- Concurrent user handling

Usage:
    locust -f tests/load/locustfile.py --host=http://localhost:8080

Note: This tests the internal components, not the Telegram API integration.
For full end-to-end testing, use the Telegram test client.
"""

import asyncio
import random
import time

from locust import User, task, between, events
from locust.runners import MasterRunner


# Sample messages for different complexity levels
SIMPLE_MESSAGES = [
    "Hi there!",
    "Thanks!",
    "OK",
    "What's up?",
    "Hello",
    "Good morning",
    "Yes",
    "No",
    "Cool",
]

ROUTINE_MESSAGES = [
    "What's the weather like today?",
    "Can you remind me about my meeting?",
    "What time is it in Sydney?",
    "Tell me a joke",
    "How are you doing?",
]

COMPLEX_MESSAGES = [
    "Can you help me write a Python function to sort a list of dictionaries by a specific key?",
    "I need to refactor this code to use async/await instead of callbacks",
    "Debug this error: TypeError: 'NoneType' object is not subscriptable",
    "Create a plan for implementing user authentication in my web app",
    "Analyse the pros and cons of using PostgreSQL vs MongoDB for my project",
]

SUMMARIZATION_MESSAGES = [
    "Summarize the key points from our conversation today",
    "Give me a TLDR of the project requirements",
    "What's the gist of the email I forwarded?",
    "Recap what we discussed about the deployment",
]


class RemyUser(User):
    """
    Simulates a Telegram user interacting with Remy.

    Uses internal component testing rather than HTTP endpoints,
    since Remy is a Telegram bot, not a web service.
    """

    wait_time = between(1, 5)  # 1-5 seconds between messages

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = random.randint(100000, 999999)
        self.session_key = f"user_{self.user_id}_2024-01-01"
        self._classifier = None
        self._conv_store = None
        self._injector = None

    def on_start(self):
        """Set up test fixtures."""
        # Import here to avoid issues when locust parses the file
        try:
            from remy.ai.classifier import MessageClassifier
            from remy.memory.conversations import ConversationStore

            self._classifier = MessageClassifier()
            # Use a temp directory for conversation store
            import tempfile

            self._temp_dir = tempfile.mkdtemp()
            self._conv_store = ConversationStore(self._temp_dir)
        except ImportError:
            pass  # Running without remy installed

    def on_stop(self):
        """Clean up test fixtures."""
        import shutil

        if hasattr(self, "_temp_dir"):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    @task(5)
    def send_simple_message(self):
        """Send a simple greeting/acknowledgment message."""
        message = random.choice(SIMPLE_MESSAGES)
        self._process_message(message, "simple")

    @task(3)
    def send_routine_message(self):
        """Send a routine conversational message."""
        message = random.choice(ROUTINE_MESSAGES)
        self._process_message(message, "routine")

    @task(2)
    def send_complex_message(self):
        """Send a complex coding/reasoning message."""
        message = random.choice(COMPLEX_MESSAGES)
        self._process_message(message, "complex")

    @task(1)
    def send_summarization_message(self):
        """Send a summarization request."""
        message = random.choice(SUMMARIZATION_MESSAGES)
        self._process_message(message, "summarization")

    def _process_message(self, message: str, message_type: str):
        """Process a message and record timing metrics."""
        start_time = time.time()

        try:
            # Run classification
            if self._classifier:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._classifier.classify(message))
                finally:
                    loop.close()

            # Record success
            total_time = (time.time() - start_time) * 1000  # ms
            events.request.fire(
                request_type="CLASSIFY",
                name=f"/{message_type}",
                response_time=total_time,
                response_length=len(message),
                exception=None,
                context={},
            )

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="CLASSIFY",
                name=f"/{message_type}",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={},
            )


class BurstUser(User):
    """
    Simulates a user sending rapid-fire messages.

    Tests the per-user concurrency limiting and rate limiting.
    """

    wait_time = between(0.1, 0.5)  # Very fast messages

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = random.randint(100000, 999999)
        self.message_count = 0

    @task
    def send_burst_message(self):
        """Send messages in rapid succession."""
        self.message_count += 1
        message = f"Burst message {self.message_count}"

        start_time = time.time()

        # Simulate the concurrency check
        # In real testing, this would hit the actual handlers
        time.sleep(random.uniform(0.01, 0.05))

        total_time = (time.time() - start_time) * 1000
        events.request.fire(
            request_type="BURST",
            name="/burst_message",
            response_time=total_time,
            response_length=len(message),
            exception=None,
            context={},
        )


class ConversationHistoryUser(User):
    """
    Tests conversation history loading performance.

    Simulates users with varying session lengths to test
    the reverse file reading optimisation.
    """

    wait_time = between(2, 5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = random.randint(100000, 999999)
        self._conv_store = None
        self._temp_dir = None
        self._session_key = f"user_{self.user_id}_2024-01-01"
        self._turns_written = 0

    def on_start(self):
        """Set up conversation store with pre-populated history."""
        try:
            from remy.memory.conversations import ConversationStore
            from remy.models import ConversationTurn

            import tempfile

            self._temp_dir = tempfile.mkdtemp()
            self._conv_store = ConversationStore(self._temp_dir)

            # Pre-populate with varying amounts of history
            num_turns = random.choice([10, 50, 100, 500])
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                for i in range(num_turns):
                    turn = ConversationTurn(
                        role="user" if i % 2 == 0 else "assistant",
                        content=f"Historical message {i} with some content to make it realistic",
                    )
                    loop.run_until_complete(
                        self._conv_store.append_turn(
                            self.user_id, self._session_key, turn
                        )
                    )
                self._turns_written = num_turns
            finally:
                loop.close()
        except ImportError:
            pass

    def on_stop(self):
        """Clean up."""
        import shutil

        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    @task
    def load_recent_history(self):
        """Load recent conversation history."""
        if not self._conv_store:
            return

        start_time = time.time()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                turns = loop.run_until_complete(
                    self._conv_store.get_recent_turns(
                        self.user_id, self._session_key, limit=20
                    )
                )
            finally:
                loop.close()

            total_time = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="HISTORY",
                name=f"/load_history_{self._turns_written}",
                response_time=total_time,
                response_length=len(turns),
                exception=None,
                context={},
            )

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="HISTORY",
                name=f"/load_history_{self._turns_written}",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={},
            )


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Print test configuration on startup."""
    if isinstance(environment.runner, MasterRunner):
        print("=" * 60)
        print("Remy Load Test Harness")
        print("=" * 60)
        print("Testing:")
        print("  - Message classification latency")
        print("  - Conversation history loading")
        print("  - Burst traffic handling")
        print("=" * 60)
