"""Coordinate one in-memory scraping run."""
from .client import discover_resource_links, fetch_all_records
from .processing import process_records
from .export import write_records
from .reporting import print_yearly_summary, create_charts


def run(url, api_url, output_path, yearly_chart_path, titles_chart_path):
    """Collect, clean, sort, export, and report using the supplied settings."""
    resource_links = discover_resource_links(url)
    names_list = []
    yearly_salary_dict = {}
    seen_records = set()
    for link in resource_links:
        resource_id = link.split('/')[-1]
        records = fetch_all_records(api_url, resource_id)
        valid_count, invalid_count = process_records(
            records, resource_id, names_list, yearly_salary_dict, seen_records
        )
        print(f'Processed link id: {resource_id}: {valid_count} valid records, {invalid_count} invalid records')
    names_list.sort(key=lambda person: person['Salary'], reverse=True)
    write_records(names_list, output_path)
    print_yearly_summary(yearly_salary_dict)
    create_charts(names_list, yearly_salary_dict, yearly_chart_path, titles_chart_path)
    print(f'Wrote {len(names_list)} records to {output_path}')
