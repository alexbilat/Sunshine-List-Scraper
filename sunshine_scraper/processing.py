"""Shared rules for reading raw CKAN/CSV rows despite inconsistent labels.

storage.models.Disclosure applies these rules to validate each row; the client
uses them to check a CSV's columns. Duplicates are decided by the database.
"""

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
