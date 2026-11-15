"""The chat agent: a hand-written tool-calling loop over Groq.

How a tool-calling model works: we send the conversation plus a "menu" of
tools (tools.TOOLS). The model either answers in plain text, or replies with
one or more tool_calls ("run top_earners with {"year": 2024}"). It never runs
anything itself. We run the matching Python function, append each result as a
role="tool" message, and ask again. Repeat until it answers in text.

This runs only on the server: the API key stays here and never reaches the
browser. No agent framework, so every step of the loop is visible below.
"""
import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from .tools import FUNCTIONS, TOOLS

logger = logging.getLogger(__name__)

# Read GROQ_API_KEY from a local .env file (gitignored). Variables already set
# in the real environment win, so a deployment can still configure it there.
load_dotenv()

# Groq serves an OpenAI-compatible API, so the official openai SDK works by
# pointing it at Groq's address. Change MODEL to try another Groq model that
# supports tool use (see https://console.groq.com/docs/tool-use).
MODEL = 'openai/gpt-oss-120b'
GROQ_BASE_URL = 'https://api.groq.com/openai/v1'

# Hard stop for the loop: a confused model could otherwise keep calling tools
# forever, and every round trip costs time and tokens.
MAX_ITERATIONS = 8

# Seconds to wait for one Groq reply (the SDK default is ten minutes).
REQUEST_TIMEOUT = 30

GAVE_UP_ANSWER = ("Sorry, I couldn't finish answering that. "
                  'Try asking a more specific question.')

SYSTEM_PROMPT = """\
You answer questions about Ontario's Public Sector Salary Disclosure (the
"Sunshine List"): people paid $100,000 or more by Ontario public-sector
employers, published every year since 1996. Each record has a first name,
last name, job title, employer, year and salary.

Rules:
- Use the tools for every fact. Never answer from memory.
- Only state numbers (salaries, counts, years) that appear in tool results.
  Do no arithmetic: no differences, totals or percentages. To show a change,
  list the values year by year and let the reader compare.
- If a tool finds nothing, say so plainly; do not guess.
- Employer names vary ("University of Waterloo" vs "University Of Waterloo"),
  so use find_employers to see the exact names before filtering by employer.
- Several people can share a name. If a name search returns different
  employers, say which person each result is, or ask which one is meant.
- These are public disclosures. Report what the data says; do not speculate
  about anyone beyond it.
- Keep answers short. Write salaries like $123,456.78.
- Reply in plain text: no Markdown, tables or bold. Use one line per item.
"""

_client = None


class ChatUnavailableError(RuntimeError):
    """The chat agent cannot run, e.g. GROQ_API_KEY is not set."""


def get_client():
    """Create the Groq client once, on first use.

    Lazily, not at import time, so the web server (and the tests) still start
    without a key; only a chat request then fails, with a clear error.
    """
    global _client
    if _client is None:
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            raise ChatUnavailableError('GROQ_API_KEY is not set')
        _client = OpenAI(base_url=GROQ_BASE_URL, api_key=api_key, timeout=REQUEST_TIMEOUT)
    return _client


def run_tool(name, arguments, connect):
    """Run one tool the model asked for and return its result as JSON text.

    Any failure (unknown tool, bad JSON, wrong arguments, database error) is
    returned as an {"error": ...} result instead of raised. The model reads it
    and can retry with better arguments, and one bad call never crashes the
    request.
    """
    try:
        if name not in FUNCTIONS:
            raise ValueError(f'unknown tool {name!r}')
        # The model sends its arguments as a JSON string, e.g. '{"year": 2024}'.
        args = json.loads(arguments or '{}')
        if not isinstance(args, dict):
            raise ValueError('arguments must be a JSON object')
        # A fresh short read-only transaction per tool call, closed before we
        # go back to the model, so a slow Groq reply never holds a connection.
        with connect() as connection:
            result = FUNCTIONS[name](connection, **args)
        return json.dumps(result)
    except Exception as error:  # deliberately broad: see the docstring
        logger.warning('Tool %s failed: %s', name, error)
        return json.dumps({'error': f'{type(error).__name__}: {error}'})


def run_agent(question, history, connect, client=None):
    """Answer one question. Returns (answer text, list of tool calls made).

    history: earlier turns as [{"role": "user"|"assistant", "content": ...}],
    so follow-up questions ("and in 2023?") have context.
    connect: a function returning a context manager that yields a read-only
    connection (the API passes read_only_connection; tests pass a fake).
    client: the OpenAI-compatible client; tests pass a fake.
    """
    client = client or get_client()

    # The whole conversation so far. The system prompt goes first so the
    # model reads the rules before anything else.
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                *history,
                {'role': 'user', 'content': question}]
    tool_calls_made = []

    for _ in range(MAX_ITERATIONS):
        # 1. Ask the model, showing it the menu of tools.
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        message = response.choices[0].message

        # 2. No tool calls means the model has answered in plain text: done.
        if not message.tool_calls:
            return message.content or '', tool_calls_made

        # 3. Record the model's request in the conversation. The tool results
        #    added next must follow the assistant message that asked for them.
        messages.append({
            'role': 'assistant',
            'content': message.content or '',
            'tool_calls': [{'id': call.id, 'type': 'function',
                            'function': {'name': call.function.name,
                                         'arguments': call.function.arguments}}
                           for call in message.tool_calls],
        })

        # 4. Run every requested tool and add each result, tagged with the id
        #    of the call it answers, so the model can match them up.
        for call in message.tool_calls:
            result = run_tool(call.function.name, call.function.arguments, connect)
            messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': result})
            tool_calls_made.append({'name': call.function.name,
                                    'arguments': call.function.arguments})

        # 5. Loop: the model now sees the results and either calls more tools
        #    or writes its answer.

    logger.warning('Agent stopped after %d iterations', MAX_ITERATIONS)
    return GAVE_UP_ANSWER, tool_calls_made
