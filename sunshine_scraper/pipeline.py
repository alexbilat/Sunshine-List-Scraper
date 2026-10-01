"""Coordinate collection; explicitly report incomplete runs."""
import logging
from urllib.parse import urlsplit
from .client import discover_resource_links, fetch_all_records
from .errors import ScraperError
from .processing import process_records
from .export import write_records
from .reporting import print_yearly_summary, create_charts

logger = logging.getLogger(__name__)


def run(url, api_url, output_path, yearly_chart_path, titles_chart_path,
        *, timeout=30, max_retries=2, backoff=1):
    """Run discovery, collection, cleaning, export, and reporting in that order.

    Return True when all resources and charts completed; False for a partial
    run. Raise ScraperError if nothing usable can be written. The CLI converts
    this result to an exit code for the shell or future automation.
    """
    # Unpacking **options forwards these dictionary entries as named arguments.
    options = {'timeout': timeout, 'max_retries': max_retries, 'backoff': backoff}
    resource_links = discover_resource_links(url, **options)
    # Fresh state for each run, shared across all resources within that run.
    names_list = []
    yearly_salary_dict = {}
    seen_records = set()
    failed_resources = []
    for link in resource_links:
        resource_path = urlsplit(link).path.rstrip('/')
        resource_id = resource_path.split('/')[-1]
        try:
            records = fetch_all_records(api_url, resource_id, **options)
        except ScraperError as error:
            # A failed resource must not prevent collecting the remaining ones.
            logger.error("Skipping failed dataset: %s", error)
            failed_resources.append(resource_id)
            continue
        process_records(records, resource_id, names_list, yearly_salary_dict, seen_records)
    # Avoid replacing a previous good export with an empty result from a failure.
    if not names_list:
        raise ScraperError("No usable records collected; existing outputs were left untouched")
    # The key function selects salary; reverse=True puts the highest salary first.
    names_list.sort(key=salary_for_sorting, reverse=True)
    write_records(names_list, output_path)
    logger.info("Wrote %s records to %s", len(names_list), output_path)
    print_yearly_summary(yearly_salary_dict)
    # Once the TSV is saved, a chart failure should not discard it.
    charts_ok = True
    try:
        create_charts(names_list, yearly_salary_dict, yearly_chart_path, titles_chart_path)
    except (OSError, ValueError) as error:
        logger.error("Chart generation failed; the TSV was saved: %s", error)
        charts_ok = False
    if failed_resources:
        logger.error("Incomplete run: %s/%s resources failed: %s", len(failed_resources),
                     len(resource_links), ', '.join(failed_resources))
    if failed_resources or not charts_ok:
        return False
    return True


def salary_for_sorting(person):
    """Give list.sort the numeric value it should compare for each record."""
    return person['Salary']
