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
    """Write usable records; return False if resources or charts failed."""
    options = dict(timeout=timeout, max_retries=max_retries, backoff=backoff)
    resource_links = discover_resource_links(url, **options)
    names_list, yearly_salary_dict, seen_records = [], {}, set()
    failed_resources = []
    for link in resource_links:
        resource_id = urlsplit(link).path.rstrip('/').split('/')[-1]
        try:
            records = fetch_all_records(api_url, resource_id, **options)
        except ScraperError as error:
            logger.error("Skipping failed dataset: %s", error)
            failed_resources.append(resource_id)
            continue
        process_records(records, resource_id, names_list, yearly_salary_dict, seen_records)
    if not names_list:
        raise ScraperError("No usable records collected; existing outputs were left untouched")
    names_list.sort(key=lambda person: person['Salary'], reverse=True)
    write_records(names_list, output_path)
    logger.info("Wrote %s records to %s", len(names_list), output_path)
    print_yearly_summary(yearly_salary_dict)
    charts_ok = True
    try:
        create_charts(names_list, yearly_salary_dict, yearly_chart_path, titles_chart_path)
    except (OSError, ValueError) as error:
        logger.error("Chart generation failed; the TSV was saved: %s", error)
        charts_ok = False
    if failed_resources:
        logger.error("Incomplete run: %s/%s resources failed: %s", len(failed_resources),
                     len(resource_links), ', '.join(failed_resources))
    return not failed_resources and charts_ok
