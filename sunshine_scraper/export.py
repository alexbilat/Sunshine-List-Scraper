"""Write the existing tab-separated output format."""

def write_records(records, output_path):
    """Write records in the supplied order and always close the file."""
    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write('Name\tSalary\tJob Title\tEmployer\tYear\tUUID\n')
        for person in records:
            output_file.write(
                f"{person['Name']}\t{person['Salary']}\t{person['Job Title']}\t{person['Employer']}\t{person['Year']}\t{person['UUID']}\n"
            )
