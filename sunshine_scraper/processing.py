"""Clean raw records and maintain deduplication across resources."""
def normalize_text(value):
    """Returns a fully clean string"""
    if value is None:
        return ''
    normalized = str(value).replace('\xa0', ' ')
    normalized = ' '.join(normalized.split())
    return normalized.strip()

def process_records(records, resource_id, names_list, yearly_salary_dict, seen_records):
    """Append accepted records to shared run state; return valid/invalid counts.

    Invalid counts preserve the original meaning: three-field company records.
    Missing years and duplicates are skipped without incrementing that count.
    """
    valid_count = 0
    invalid_count = 0
    for person in records:
        if len(person) == 3:
            invalid_count += 1
            continue

        raw_salary = person.get('Salary Paid')
        if raw_salary is None:
            raw_salary = person.get('Salary')

        if raw_salary is not None:
            try:
                clean_salary = str(raw_salary).replace('$', '').replace(',', '').strip()
                salary_float = float(clean_salary)
            except ValueError:
                salary_float = 0.0
        else:
            salary_float = 0.0

        year = (
            person.get('Calendar Year')
            or person.get('Year')
            or person.get('Calendar year')
            or person.get('calendar_year')
        )

        if year is None or str(year).strip().lower() in ('none', 'unknown', ''):
            continue

        first_name = normalize_text(person.get('First Name'))
        last_name = normalize_text(person.get('Last Name'))
        job_title = normalize_text(person.get('Job Title'))
        employer = normalize_text(person.get('Employer'))
        year_str = normalize_text(year)

        record_key = (first_name.lower(), last_name.lower(), job_title.lower(), employer.lower(), year_str, salary_float)
        if record_key in seen_records:
            continue
        seen_records.add(record_key)

        names_list.append({
            'Name' : f"{first_name} {last_name}",
            'Salary' : salary_float,
            'Job Title' : job_title,
            'Employer' : employer,
            'Year' : year_str,
            'UUID' : resource_id})

        yearly_salary_dict.setdefault(year_str, []).append(salary_float)
        valid_count += 1

    return valid_count, invalid_count
