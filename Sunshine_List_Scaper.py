#########################################################
# NAME: Alex_Bilat
# COURSE: ICS4U
# FILE: Sunshine_List_Scraper.py
# DESCRIPTION: Main script 
#########################################################

# Importing
from config import *

# For character stripping later
sys.stdout.reconfigure(encoding="utf-8")

# Main
response = requests.get(url)
if response.status_code != 200: # If request is invalid
    print(f'Error in url: {url}')
    sys.exit()

html_content = response.content # Get content of page
soup = BeautifulSoup(html_content, 'html.parser')
soup.prettify() # Self explanatory

links = soup.find_all('div', class_ = 'body-field') # Find all the links

resource_links = [] # List of URLs

for link in soup.find_all("a", href = True):
    url_text = link.get_text().strip() # Get html code
    url = link['href'] # Get all links

    if 'public-sector-salary-disclosure' in url.lower() and 'resource' in url.lower(): # Filter out a lot of links
        resource_links.append(url) # Add the right url to the link_list

# Structure for this list is a list with a bunch of hashmaps inside. The hashmap will have certain information about each person. We will sort this list later. 

names_list = [] # Master dictionary
yearly_salary_dict = {} # Dict mapping a year to a list of all the salaries of that year. WIll be used later to calculate averages and whatnot. 
seen_records = set() # Track records already added to avoid duplicates across UUIDs


def fetch_all_records(api_url, resource_id):
    """Returns all records for one specific UUID"""
    records = [] # List of people per year
    limit = 100000 # Max number for requests on ontario KCAN API
    offset = 0

    while True:
        # I have to use an offset here because the api is limited to the first 100k people. 
        # With the offset, I can parse through the next 100k people untill the list runs out. 
        query_parameters = {
            'resource_id': resource_id,
            'limit': limit, # 100k cap
            'offset': offset,
        }
        response = requests.get(api_url, params=query_parameters) 
        if response.status_code != 200: # If bad response
            print(f'Error fetching {resource_id} at offset {offset}: {response.status_code}') # Return error code
            break

        data = response.json() # Convert to python dict
        batch = data['result']['records'] # Get people
        records.extend(batch) # add the next batch to the end the records (get to the next part of the list)

        if len(batch) < limit:
            break # Can't go over limit :(

        offset += limit # Start at next 

    return records

def normalize_text(value):
    """Returns a fully clean string"""
    if value is None:
        return ''
    normalized = str(value).replace('\xa0', ' ')  # normalize non-breaking spaces
    normalized = ' '.join(normalized.split())     # collapse all whitespace
    return normalized.strip()

for link in resource_links:
    resource_id = link.split('/')[-1] # Get the UUID
    records = fetch_all_records(api_url, resource_id) # Get records for the UUID above

    temp_salary_list = [] # Used to hold all of the salaries in a year
    valid_count = 0
    invalid_count = 0

    for person in records:
        if len(person) == 3: # Ignore the companies pages (there's weird pages that lists companies instead of people)
            invalid_count += 1
            continue

        raw_salary = person.get('Salary Paid') # Get salary
        if raw_salary is None:
            raw_salary = person.get('Salary')

        if raw_salary is not None: # Strip weird characters
            try:
                clean_salary = str(raw_salary).replace('$', '').replace(',', '').strip() # Strip to replace weird symbols that gov of ontario sometimes likes to add
                salary_float = float(clean_salary)
            except ValueError:
                salary_float = 0.0  # if data is weird or corrupted or someone made a mistake
        else:
            salary_float = 0.0

        year = ( # All the variations of the same thing. Thank you Government of Ontario!! Your api is very annoying to deal with.
            person.get('Calendar Year')
            or person.get('Year')
            or person.get('Calendar year')
            or person.get('calendar_year')
        )

        if year is None or str(year).strip().lower() in ('none', 'unknown', ''):
            continue  # Ignore people with a missing or unknown year

        first_name = normalize_text(person.get('First Name')) # Removing weird white space characters to avoid dupes
        last_name = normalize_text(person.get('Last Name'))
        job_title = normalize_text(person.get('Job Title'))
        employer = normalize_text(person.get('Employer'))
        year_str = normalize_text(year)

        record_key = (first_name.lower(), last_name.lower(), job_title.lower(), employer.lower(), year_str, salary_float)
        if record_key in seen_records:
            continue  # Skip duplicate records across UUIDs
        seen_records.add(record_key) # Keep track of all

        names_list.append({ # Append to list 
            'Name' : f"{first_name} {last_name}",
            'Salary' : salary_float,
            'Job Title' : job_title,
            'Employer' : employer, 
            'Year' : year_str,
            'UUID' : resource_id})

        temp_salary_list.append(salary_float) # Add the salary to the temp list (used later to calculate averages)
        yearly_salary_dict.setdefault(year_str, []).append(salary_float) # Check if year exists. If not, then map a year to an empty list which will fill later. If it does exist, then append the salary list to the year. 
        valid_count += 1

    print(f'Processed link id: {resource_id}: {valid_count} valid records, {invalid_count} invalid records') # Used to show the checking
 
names_list = sorted(names_list, key=lambda x: x['Salary'], reverse=True) # Sort the list. Might try do manual sorting if there's time (There was no time)

try:
    output_file = open(output_path, 'w', encoding='utf-8') # Open file
except FileNotFoundError as e:
    print(f'Could not find file: {e}')
    sys.exit()

output_file.write('Name\tSalary\tJob Title\tEmployer\tYear\tUUID\n') # Quick title

# Write output to file
for person in names_list:
    output_file.write( # Populate the file
        f"{person['Name']}\t{person['Salary']}\t{person['Job Title']}\t{person['Employer']}\t{person['Year']}\t{person['UUID']}\n"
    )

# Print the averages at the end
for year in sorted(yearly_salary_dict, reverse=True): # Sort the yearly salary dict
    salaries = yearly_salary_dict[year]
    average = sum(salaries) / len(salaries) if salaries else 0 # If list is populated, then find sum, otherwise 0. 
    print(f'{year}: Average: {average:.2f} Number of people: {len(salaries)}') # Print averages



# Output into graphs
years_sorted = sorted(yearly_salary_dict.keys()) # List of years
averages = [sum(yearly_salary_dict[y]) / len(yearly_salary_dict[y]) for y in years_sorted] # Find average per year
counts   = [len(yearly_salary_dict[y]) for y in years_sorted] # Count num of people per year

fig, ax1 = plt.subplots(figsize=(14, 6)) # Just config the graph
ax1.bar(years_sorted, counts, color='steelblue', alpha=0.4, label='# of People') # Bar style on the left
ax1.set_ylabel('Number of People', color='steelblue') # Self explanatory
ax1.tick_params(axis='x', rotation=45) # Grid line appearance
 
ax2 = ax1.twinx() # Create twin axis cuz we're tracking 2 variables
ax2.plot(years_sorted, averages, color='crimson', marker='o', linewidth=2, label='Avg Salary') # Style for lines
ax2.set_ylabel('Average Salary ($)', color='crimson') # Style of label
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}')) # Handles scaling

plt.title('Ontario Sunshine List — Average Salary & Headcount by Year') # Set title
fig.tight_layout()
plt.savefig('chart_yearly.png', dpi=150) # save to file
plt.close()

#  Top 10 job titles 
title_counts = Counter(p['Job Title'] for p in names_list if p['Job Title']) # Counter module, used for counting (duh)
top_titles = title_counts.most_common(10) # Get 10 most common titles as well as their names. All stored as tulpes in top_tiles
labels, values = zip(*top_titles) # Unzip the top titles, to get the labels and values (job title and count). This is organized well

fig, ax = plt.subplots(figsize=(12, 6)) # Sizing
ax.barh(labels[::-1], values[::-1], color='teal') # Style for bars
ax.set_xlabel('Number of Appearances') # Self explanatory 
ax.set_title('Top 10 Most Common Job Titles on the Sunshine List') # Also self explanatory
fig.tight_layout() # Just adjust the padding slightly
plt.savefig('chart_titles.png', dpi=150) # Save! DPI is resolution per square inch. I think 150 is fine

plt.close() # close!
output_file.close() # Close

print(f'Wrote {len(names_list)} records to {output_path}') # Show number of people that we found!

# Gotta run: pip install matplotlib


