"""Turn raw API rows into consistent records before export and reporting.

Bad rows are skipped individually. The pipeline supplies collections shared
across resources so duplicate rows cannot enter the totals twice.
"""
import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


def normalize_text(value):
    """Return plain text with repeated whitespace collapsed.

    Missing values become empty strings. Containers and booleans are rejected
    because converting them to text would hide an unexpected source format.
    """
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Expected a text or numeric scalar")

    text = str(value).replace('\xa0', ' ')
    words = text.split()  # Without an argument, split handles any whitespace.
    return ' '.join(words)


def clean_record(person, resource_id):
    """Return (cleaned record, duplicate key), or raise for an invalid row.

    Identity fields, a four-digit year, and a usable salary are required.
    A missing job title is allowed and will be reported by process_records.
    """
    if not isinstance(person, dict):
        raise ValueError("row is not an object")

    first_name = normalize_text(person.get('First Name'))
    last_name = normalize_text(person.get('Last Name'))
    job_title = normalize_text(person.get('Job Title'))
    employer = normalize_text(person.get('Employer'))
    if not first_name or not last_name or not employer:
        raise ValueError("missing first name, last name, or employer")

    # Ontario uses different year column names in different datasets.
    # Keep the same priority: the first value that is neither None nor '' wins.
    year_fields = ('Calendar Year', 'Year', 'Calendar year', 'calendar_year')
    raw_year = None
    for field_name in year_fields:
        value = person.get(field_name)
        if value is not None and value != '':
            raw_year = value
            break

    year = normalize_text(raw_year)
    if len(year) != 4 or not year.isascii() or not year.isdigit():
        raise ValueError("missing or invalid four-digit year")

    raw_salary = person.get('Salary Paid')
    if raw_salary is None:
        raw_salary = person.get('Salary')
    salary_text = normalize_text(raw_salary)
    salary_text = salary_text.replace('$', '').replace(',', '')
    salary = float(salary_text)  # Invalid numbers raise ValueError for the caller.
    if not math.isfinite(salary) or salary < 0:
        raise ValueError("salary must be finite and nonnegative")

    # UUID is deliberately excluded: the same row can occur in two resources.
    # Lowercase identity fields for matching, but keep their display spelling.
    duplicate_key = (
        first_name.lower(),
        last_name.lower(),
        job_title.lower(),
        employer.lower(),
        year,
        salary,
    )
    record = {
        'Name': f"{first_name} {last_name}",
        'Salary': salary,
        'Job Title': job_title,
        'Employer': employer,
        'Year': year,
        'UUID': resource_id,
    }
    return record, duplicate_key


def process_records(records, resource_id, names_list, yearly_salary_dict, seen_records):
    """Update the three shared collections; return valid and invalid counts.

    names_list holds accepted records, yearly_salary_dict groups salaries,
    and seen_records holds duplicate keys from every resource in this run.
    Duplicate counts are logged separately from invalid-row counts.
    """
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0
    missing_title_count = 0
    invalid_reasons = Counter()  # Count each reason for one summary per resource.

    for row_index, person in enumerate(records):
        try:
            record, duplicate_key = clean_record(person, resource_id)
        except (ValueError, TypeError, OverflowError) as error:
            invalid_count += 1
            invalid_reasons[str(error)] += 1
            logger.debug("Resource %s row %s skipped: %s", resource_id, row_index, error)
            continue  # Reject this row, then attempt the next one.

        if duplicate_key in seen_records:
            duplicate_count += 1
            continue

        # Update all totals only after validation and duplicate checking succeed.
        seen_records.add(duplicate_key)
        names_list.append(record)
        year = record['Year']
        if year not in yearly_salary_dict:
            yearly_salary_dict[year] = []
        yearly_salary_dict[year].append(record['Salary'])
        valid_count += 1
        if not record['Job Title']:
            missing_title_count += 1

    logger.info("Resource %s: %s valid, %s invalid, %s duplicates", resource_id,
                valid_count, invalid_count, duplicate_count)
    if invalid_count:
        logger.warning("Resource %s skipped invalid rows: %s", resource_id, dict(invalid_reasons))
    if missing_title_count:
        logger.warning("Resource %s: %s accepted rows have no job title", resource_id, missing_title_count)
    return valid_count, invalid_count
