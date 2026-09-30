"""Discover Ontario datasets and fetch paginated CKAN records."""
import requests
from bs4 import BeautifulSoup

def discover_resource_links(url):
    """Find disclosure resource links in their original page order."""
    response = requests.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"Error in url: {url}")
    soup = BeautifulSoup(response.content, "html.parser")
    return [link["href"] for link in soup.find_all("a", href=True)
            if "public-sector-salary-disclosure" in link["href"].lower()
            and "resource" in link["href"].lower()]

def fetch_all_records(api_url, resource_id):
    """Returns all records for one specific UUID"""
    records = []
    limit = 100000
    offset = 0

    while True:


        query_parameters = {
            'resource_id': resource_id,
            'limit': limit,
            'offset': offset,
        }
        response = requests.get(api_url, params=query_parameters)
        if response.status_code != 200:
            print(f'Error fetching {resource_id} at offset {offset}: {response.status_code}')
            break

        data = response.json()
        batch = data['result']['records']
        records.extend(batch)

        if len(batch) < limit:
            break

        offset += limit

    return records

