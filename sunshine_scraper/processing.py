"""Validate raw rows, normalize fields, and deduplicate across resources."""
import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


def normalize_text(value):
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Expected a text or numeric scalar")
    return ' '.join(str(value).replace('\xa0', ' ').split())


def clean_record(person, resource_id):
    """Return a clean record and its identity key, or explain why it is invalid."""
    if not isinstance(person, dict):
        raise ValueError("row is not an object")
    fields = {name: normalize_text(person.get(name))
              for name in ('First Name', 'Last Name', 'Job Title', 'Employer')}
    if not fields['First Name'] or not fields['Last Name'] or not fields['Employer']:
        raise ValueError("missing first name, last name, or employer")
    year = next((person.get(key) for key in ('Calendar Year', 'Year', 'Calendar year', 'calendar_year')
                 if person.get(key) is not None and person.get(key) != ''), None)
    year = normalize_text(year)
    if len(year) != 4 or not year.isascii() or not year.isdigit():
        raise ValueError("missing or invalid four-digit year")
    raw_salary = person.get('Salary Paid')
    if raw_salary is None:
        raw_salary = person.get('Salary')
    salary = float(normalize_text(raw_salary).replace('$', '').replace(',', ''))
    if not math.isfinite(salary) or salary < 0:
        raise ValueError("salary must be finite and nonnegative")
    key = tuple(fields[name].lower() for name in fields) + (year, salary)
    record = {'Name': f"{fields['First Name']} {fields['Last Name']}",
              'Salary': salary, 'Job Title': fields['Job Title'],
              'Employer': fields['Employer'], 'Year': year, 'UUID': resource_id}
    return record, key


def process_records(records, resource_id, names_list, yearly_salary_dict, seen_records):
    """Skip invalid and repeated rows, with an aggregate quality summary."""
    valid_count = invalid_count = duplicates = missing_titles = 0
    reasons = Counter()
    for index, person in enumerate(records):
        try:
            record, key = clean_record(person, resource_id)
        except (ValueError, TypeError, OverflowError) as error:
            invalid_count += 1
            reasons[str(error)] += 1
            logger.debug("Resource %s row %s skipped: %s", resource_id, index, error)
            continue
        if key in seen_records:
            duplicates += 1
            continue
        seen_records.add(key)
        names_list.append(record)
        yearly_salary_dict.setdefault(record['Year'], []).append(record['Salary'])
        valid_count += 1
        missing_titles += not record['Job Title']
    logger.info("Resource %s: %s valid, %s invalid, %s duplicates", resource_id,
                valid_count, invalid_count, duplicates)
    if invalid_count:
        logger.warning("Resource %s skipped invalid rows: %s", resource_id, dict(reasons))
    if missing_titles:
        logger.warning("Resource %s: %s accepted rows have no job title", resource_id, missing_titles)
    return valid_count, invalid_count
