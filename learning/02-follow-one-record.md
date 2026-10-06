# 2. Follow one resource and one disclosure

The URLs/people below are illustrative. `example-resource` is a stand-in for a real
CKAN resource UUID; do not expect that identifier to work against Ontario's API.

## 1. From startup to a link

Direct execution calls the CLI's `main()`, which configures logging and calls
`pipeline.run()`. That calls `client.discover_resource_links(config.url)`.

Suppose the downloaded HTML contains:

```html
<a href="/dataset/public-sector-salary-disclosure/resource/example-resource/">
  Download records
</a>
```

`request_page()` returns a successful HTML response. BeautifulSoup finds the anchor.
The URL text passes discovery's two substring checks. `urlsplit(href).path` removes
query/fragment parts; `rstrip('/')` removes a trailing slash; `split('/')[-1]`
extracts `example-resource`. Repeated links to that ID count once.

Discovery returns a list of href strings, not records. The pipeline extracts the
same final ID and passes it to `fetch_all_records()`.

## 2. A resource becomes several requests

The first request parameters are:

```python
{
    'resource_id': 'example-resource',
    'limit': 100000,
    'offset': 0,
}
```

`requests.get(api_url, params=query_parameters, ...)` encodes them in the request URL.
The HTML landing-page URL and the CKAN API URL have different jobs. We do not fetch
the full records by opening the resource href and parsing a displayed table.

Suppose this resource contains 250,001 rows and the API honours the requested size:

| Request | Offset | Returned rows | Next action |
| --- | ---: | ---: | --- |
| 1 | 0 | 100,000 | Append batch; advance offset |
| 2 | 100,000 | 100,000 | Append batch; advance offset |
| 3 | 200,000 | 50,001 | Append batch; short page ends resource |

If the number is an exact multiple of the page size, an additional empty page ends
the loop. The current stopping rule relies on a short page; it does not use the
response's reported total to prove completeness.

HTTP 200 is only the first check. `response.json()` must decode, `success` must be
True, and `result.records` must be a list. Only a validated batch is appended.

The function accumulates all pages for this resource in a list. It is not streaming
individual pages into persistent storage yet.

## 3. The raw API row

Inside `result.records`, suppose one object is:

```python
{
    'First Name': ' Alex\xa0 ',
    'Last Name': ' Example ',
    'Job Title': ' Software   Developer ',
    'Employer': ' Example Hospital ',
    'Calendar Year': '2024',
    'Salary Paid': '$123,456.78',
}
```

The `\xa0` escape represents a non-breaking space. This Python dictionary is how
the decoded JSON object appears in memory. The example is fictional.

After the whole resource downloads, the pipeline calls `process_records()` with the
raw rows, the resource ID, and the same three accepted-data collections used for
the other resources.

## 4. `clean_record()` transforms the row

First, `normalize_text()` cleans the name/title/employer values:

| Raw value | Normalized value |
| --- | --- |
| `' Alex\xa0 '` | `'Alex'` |
| `' Example '` | `'Example'` |
| `' Software   Developer '` | `'Software Developer'` |
| `' Example Hospital '` | `'Example Hospital'` |

`split()` without an argument splits on whitespace and discards surrounding
whitespace. Joining those words with one space produces predictable text.

Year selection checks `Calendar Year`, `Year`, `Calendar year`, and `calendar_year`
in that order, using the first value that is neither None nor an empty string.
`'2024'` becomes a valid four-digit year string. A nonempty but invalid earlier alias
is rejected; it does not silently fall through to a later alias.

For salary:

```text
'$123,456.78' -> '123456.78' -> float value 123456.78
```

The current representation is a Python float, not integer cents. It passes the
finite/nonnegative check. A database's exact-money design will require a deliberate
change to this conversion; see [chapter 4](04-postgresql-architecture.md). The new
PostgreSQL adapter reads exact cents directly from the raw source, separately from
this existing export path.

The display record is now:

```python
{
    'Name': 'Alex Example',
    'Salary': 123456.78,
    'Job Title': 'Software Developer',
    'Employer': 'Example Hospital',
    'Year': '2024',
    'UUID': 'example-resource',
}
```

The duplicate key returned alongside it is:

```python
(
    'alex',
    'example',
    'software developer',
    'example hospital',
    '2024',
    123456.78,
)
```

The display record retains capitalization. Matching uses lowercased identity text.
First and last names are separate in the key even though the exported Name joins
them. No source UUID is in the key.

## 5. Acceptance changes three collections

If that key is absent from `seen_records`, `process_records()`:

1. Adds the key to `seen_records`.
2. Appends the record dictionary to `names_list`.
3. Appends the salary to `yearly_salary_dict['2024']`, creating the list if needed.
4. Increments its accepted count for this resource.

For just this row, the state is:

```python
names_list = [record]
yearly_salary_dict = {'2024': [123456.78]}
seen_records = {duplicate_key}
```

The function mutates the caller's list/dictionary/set objects. It does not copy
them and the pipeline does not need to assign a returned list.

If a later resource contains the same disclosure with `First Name` written as
`'alex'`, the normalized key matches. That second row updates none of these
collections. The retained display record keeps the first accepted resource UUID.
This is within-run deduplication; the set resets when the next run starts.

## 6. Sorting and export

After all resources, `salary_for_sorting(record)` returns 123456.78. Python sorts
all accepted dictionaries by this numeric value, highest first.

`write_records()` publishes this TSV header and row, with real tab characters
between columns:

```text
Name\tSalary\tJob Title\tEmployer\tYear\tUUID
Alex Example\t123456.78\tSoftware Developer\tExample Hospital\t2024\texample-resource
```

The `\t` symbols above make delimiters visible; they are not literally backslash-t
in the output. A TSV-aware reader handles the quoting performed by `DictWriter`.

The writer builds a temporary file first, closes it, then replaces the destination.
Sorting is a pipeline decision; `write_records()` writes the order it receives.

## 7. Reporting uses the same accepted row

For a year containing only this record, its accepted count is 1 and its mean is
123456.78. With more disclosures, the mean is their salary sum divided by count.

The yearly chart includes that salary in 2024's average and adds one to its count.
The title chart counts one appearance of `Software Developer`. It counts disclosure
appearances, so a person listed in multiple years contributes multiple appearances.

If all datasets downloaded and chart work completed without a caught failure,
`run()` returns True, `main()` returns 0, and the terminal receives exit code 0.
Rejected raw rows are still possible in a successful run; inspect warnings.

## Alternatives at the failure points

- A timeout may retry before any response exists. A broken JSON body fails the
  dataset rather than entering row processing.
- A missing employer or invalid salary rejects this row, not all remaining rows.
- A missing title is allowed as an empty string and counted in a warning.
- A failure on this resource's later page prevents all its rows reaching processing.
- A chart error after TSV export leaves the TSV available and makes the run incomplete.

Try explaining this same path for a row with `Year=2023`, `Salary='150000'`, no
`Calendar Year`, and no job title. It should use the fallbacks, accept the row,
and exclude its empty title from the title chart.
