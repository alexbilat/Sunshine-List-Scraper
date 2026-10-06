# 3. Python constructs, errors, and verification

Use this chapter beside the source. The examples refer to actual patterns in the
application rather than introducing a separate framework.

## Imports and startup

`import config` exposes settings as `config.url` and `config.output_path`. An
explicit module name makes their origin visible. Each implementation module imports
the libraries it uses. A relative import such as `from .errors import ScraperError`
means the `errors` module in the same `sunshine_scraper` package.

Python executes a module's top-level statements during import. Defining a function
does not execute its body. The `if __name__ == '__main__'` guard keeps CLI work from
running merely because a test imports the file. `main()` is a conventional name;
the guard explicitly calls it. `raise SystemExit(main())` hands the returned number
to the shell. This is why imports must not download data or open databases.

## Data structures in this app

| Structure | Concrete use | Reason |
| --- | --- | --- |
| list | `names_list`, fetched pages, yearly salary lists | Ordered collections; append and sort |
| dict | A cleaned record; salaries grouped by year | Look up a value using a meaningful key |
| set | `seen_records`, discovered resource IDs | Membership checks without repeated list scans |
| tuple | A six-part duplicate key | Immutable values can be used as a set key |
| Counter | Invalid reasons and title frequencies | Count occurrences with convenient defaults |

A record dictionary is not the same as a database table. The dictionary exists in
memory for this Python process. A database file can retain rows after the process ends.

When a function receives a list, dict, or set and mutates it, the caller observes
the change. That is how `process_records()` updates pipeline state. It does not
reassign or silently replace the caller's collections.

## Syntax that is easy to miss

| Pattern | Meaning here |
| --- | --- |
| `def run(...):` | Define a function; indentation identifies its body |
| `record['Salary']` | Required dictionary lookup; missing key raises KeyError |
| `person.get('Salary Paid')` | Optional lookup; default is None when absent |
| `isinstance(value, dict)` | Check the type before relying on dictionary operations |
| `value is None` | Check the missing-value singleton |
| `data.get('success') is True` | Require the Boolean True rather than a truthy string/number |
| `a or b` | Short-circuit Boolean expression; not a generic schema validator |
| `continue` | Skip the remainder of this iteration and attempt the next item |
| `return records` | Leave the function and give the caller its result |
| `raise ScraperError(...)` | Stop normal flow with an expected scraper exception |
| `raise ... from error` | Preserve the original exception as the cause |
| `record, duplicate_key = clean_record(...)` | Unpack two returned values |
| `enumerate(records)` | Iterate with an index for diagnostic logging |
| `records.extend(batch)` | Add each batch item, rather than one nested list |
| `range(total_attempts)` | Produce attempt numbers from zero up to one less than the count |
| `records[-page_size:]` | Slice the most recent page-sized part of the list |
| `resource_path.split('/')[-1]` | Take the final slash-separated path segment |
| `reverse=True` | Sort descending instead of ascending |
| `f'${value:,.0f}'` | Format a number with commas, no decimal digits, and a dollar sign |

The star in `def request_page(url, *, timeout=30, ...)` requires those options to
be named by callers. It does not create a pointer. `**request_options` in a function
definition collects named arguments into a dictionary. `**options` in a call expands
dictionary entries into named arguments. Thus `{'timeout': 30}` becomes `timeout=30`.

`bool` is a subclass of `int`, so `isinstance(True, int)` is True. Request-setting
validation explicitly rejects booleans to avoid treating True as a one-second timeout.
`math.isfinite()` rejects NaN and infinity. Salary validation accepts zero but rejects
negative/non-finite values; it does not enforce a $100,000 threshold itself.

## HTTP, JSON, and row validation are separate

An HTTP status describes the request response. HTTP 200 does not guarantee that the
body is valid JSON or that CKAN succeeded. JSON decoding gives Python objects; shape
checks make sure they have the fields and container types the program expects.
Row cleaning then validates each disclosure. These are three different boundaries.

`request_page()` retries timeouts, connection errors, and these statuses:

| Status | General meaning |
| --- | --- |
| 429 | Too many requests / rate limiting |
| 500 | Internal server error |
| 502 | Bad gateway |
| 503 | Service unavailable |
| 504 | Gateway timeout |

Other non-200 statuses stop immediately under this code's policy. For example,
repeating a 404 usually will not fix a missing endpoint. These categories are a
policy decision, not a claim that every request failure is recoverable.

With `max_retries=2`, there are at most three attempts: initial request, retry 1,
retry 2. `backoff=1` gives waits of one second and two seconds. There is no wait
after the final failure. Request timeouts apply to connection/read waiting, not a
deadline for the entire scrape. The current retry code does not interpret Retry-After
headers or retry JSON/schema errors after receiving HTTP 200.

## `try`, `except`, `else`, and `finally`

`request_page()` uses a try around the request. An except clause handles matching
exceptions. Its else block examines status codes only when the request did not
raise. The failed-attempt code then either sleeps or raises an exhausted-attempt error.

`process_records()` catches only the expected conversion/type errors around one row.
Putting that boundary inside the loop keeps one bad row from rejecting the entire
resource. It validates and deduplicates before updating totals.

`pipeline.run()` catches expected resource-download errors and continues the next
resource. It separately catches chart file/value errors after the TSV has been saved.
The CLI is the outer boundary for remaining failures and traceback logging.

`finally` runs cleanup when execution leaves its try block, whether it succeeded or
raised. Export removes temporary files; reporting closes figures after save attempts;
the query practice module closes its database connection after success or failure.
Cleanup does not suppress the exception or undo previously published outputs.

## Logging replaces ad hoc progress prints

Each module creates `logging.getLogger(__name__)`. The CLI configures handlers once.
The module name makes it clear whether an issue occurred in downloading, processing,
export, or reporting. The configured level controls which messages are visible.

| Level | Existing use |
| --- | --- |
| DEBUG | Individual rejected rows, repeated links, API-page diagnostics |
| INFO | Resource counts, export completion, yearly summaries |
| WARNING | Retries, rejected-row summaries, missing titles, user interruption |
| ERROR | Skipped datasets, incomplete runs, expected stopping failures |
| CRITICAL | Available in Python but unused in this application |

`logger.exception(...)` logs at ERROR and includes the current exception's traceback.
The broad exception handler at the CLI does not silently discard unexpected bugs.

Calls such as `logger.info('Wrote %s records', len(records))` let logging format
arguments when it emits the message. Logging is separate from returning a completion
status; a logged warning is not automatically an unsuccessful process.

## Reading the tests

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

The test runner imports test modules and runs `test_...` methods. Existing tests use
synthetic responses, patch network requests and retry sleeps, and write real TSV/PNG
files only into temporary directories. Some logged errors are intentional fixtures.
They are not failures unless assertions fail or the runner reports an error.

`Mock` supplies expected methods/attributes without a real server. `patch` temporarily
replaces the name looked up by the module under test. `side_effect` can raise an
exception or supply different outcomes to successive calls. `assertRaises` verifies
that a failure really occurs; `assertLogs` verifies diagnostic messages.

The existing suite checks HTTP retries, discovery, pagination, malformed responses,
row validation, cross-resource duplicates, fallback fields, incomplete runs, output
preservation, quoting, chart cleanup, and CLI status. The database tests added in
this update check safe imports, missing-file protection, filtering/limit/order, and
connection cleanup after an invalid schema. They do not prove live API coverage or
database import functionality; neither requires a full live scrape.

The `tests` directory is now available to version control so new PostgreSQL checks
can travel with the code. Offline checks cover exact cents, content fingerprints,
configuration, safe imports, and query input boundaries. Real PostgreSQL checks
are opt-in; see [chapter 4](04-postgresql-architecture.md).

## Things to explain before making the database change

Explain why a timeout retries but an invalid row is skipped; why a partial dataset
must not be labelled complete; why outputs can coexist with exit 1; and how the
query module can be imported safely without touching a database. These are decisions
about behaviour, not just Python syntax.
