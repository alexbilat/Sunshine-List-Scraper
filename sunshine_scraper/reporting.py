"""Report cleaned data; this module does not download or validate raw rows."""
import logging
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)


def print_yearly_summary(yearly_salary_dict):
    """Log an average and accepted-record count for each year, newest first."""
    for year in sorted(yearly_salary_dict, reverse=True):
        salaries = yearly_salary_dict[year]
        if salaries:
            average = sum(salaries) / len(salaries)
        else:
            average = 0
        logger.info('%s: Average: %.2f Number of people: %s', year, average, len(salaries))


def create_charts(names_list, yearly_salary_dict, yearly_chart_path, titles_chart_path):
    """Save yearly totals and the ten most frequent nonempty job titles.

    Inputs are the pipeline's accepted records and grouped salaries. File errors
    propagate to the pipeline, which can report failure while keeping the TSV.
    """
    # All three lists must use the same year order so each bar and point align.
    years_sorted = sorted(yearly_salary_dict.keys())
    averages = []
    counts = []
    for year in years_sorted:
        salaries = yearly_salary_dict[year]
        averages.append(sum(salaries) / len(salaries))
        counts.append(len(salaries))

    figure, count_axis = plt.subplots(figsize=(14, 6))
    count_axis.bar(years_sorted, counts, color='steelblue', alpha=0.4, label='# of People')
    count_axis.set_ylabel('Number of People', color='steelblue')
    count_axis.tick_params(axis='x', rotation=45)

    # Headcount and salary have different units. twinx shares the horizontal
    # year positions but supplies a separate salary scale on the right.
    salary_axis = count_axis.twinx()
    salary_axis.plot(years_sorted, averages, color='crimson', marker='o',
                     linewidth=2, label='Avg Salary')
    salary_axis.set_ylabel('Average Salary ($)', color='crimson')

    def format_salary_tick(value, position):
        # Matplotlib passes a tick position too; only its numeric value is needed.
        return f'${value:,.0f}'

    salary_axis.yaxis.set_major_formatter(mticker.FuncFormatter(format_salary_tick))
    plt.title('Ontario Sunshine List — Average Salary & Headcount by Year')
    figure.tight_layout()  # Adjust spacing to keep labels within the image.
    try:
        figure.savefig(yearly_chart_path, dpi=150)
    finally:
        # Release the figure even if saving fails (e.g. a missing directory).
        plt.close(figure)

    # Counter maps a title to the number of accepted records with that title.
    title_counts = Counter()
    for person in names_list:
        title = person['Job Title']
        if title:
            title_counts[title] += 1
    top_titles = title_counts.most_common(10)
    if not top_titles:
        logger.warning("No job titles available; title chart was not written")
        return  # Leave any previously saved title chart untouched.

    # most_common returns largest first. Reverse the order so the largest bar
    # appears at the top of a horizontal chart, whose first bar is at the bottom.
    labels = []
    values = []
    for title, count in reversed(top_titles):
        labels.append(title)
        values.append(count)

    figure, title_axis = plt.subplots(figsize=(12, 6))
    title_axis.barh(labels, values, color='teal')
    title_axis.set_xlabel('Number of Appearances')
    title_axis.set_title('Top 10 Most Common Job Titles on the Sunshine List')
    figure.tight_layout()
    try:
        figure.savefig(titles_chart_path, dpi=150)
    finally:
        plt.close(figure)
