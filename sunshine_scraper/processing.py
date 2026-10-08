"""Turn raw API rows into consistent records before export and reporting.

Bad rows are skipped individually. The pipeline supplies collections shared
across resources so duplicate rows cannot enter the totals twice.
"""
import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)

# Column labels changed between Ontario's yearly publications. These aliases
# describe the same information, in order of preference when both are present.
FIELD_ALIASES = {
    'first_name': ('first name',),
    'last_name': ('last name', 'surname'),
    'job_title': ('job title', 'position'),
    'employer': ('employer',),
    'year': ('calendar year', 'year'),
    'salary': ('salary paid', 'salary'),
}


def normalize_field_name(name):
    """Match column labels despite capitals, underscores, spaces, or a BOM."""
    if not isinstance(name, str):
        raise ValueError("column name must be text")
    return ' '.join(name.strip().lstrip('\ufeff').replace('_', ' ').split()).casefold()


def get_record_field(fields, name):
    """Read the first nonempty alias from a dictionary of normalized columns."""
    for alias in FIELD_ALIASES[name]:
        value = fields.get(alias)
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return None


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

    fields = {normalize_field_name(name): value for name, value in person.items()}
    first_name = normalize_text(get_record_field(fields, 'first_name'))
    last_name = normalize_text(get_record_field(fields, 'last_name'))
    job_title = normalize_text(get_record_field(fields, 'job_title'))
    employer = normalize_text(get_record_field(fields, 'employer'))
    if not first_name or not last_name or not employer:
        raise ValueError("missing first name, last name, or employer")

    year = normalize_text(get_record_field(fields, 'year'))
    if len(year) != 4 or not year.isascii() or not year.isdigit():
        raise ValueError("missing or invalid four-digit year")

    salary_text = normalize_text(get_record_field(fields, 'salary'))
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
