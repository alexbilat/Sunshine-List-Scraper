"""Console summaries and matplotlib charts for collected records."""
import logging
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

def print_yearly_summary(yearly_salary_dict):
    for year in sorted(yearly_salary_dict, reverse=True):
        salaries = yearly_salary_dict[year]
        average = sum(salaries) / len(salaries) if salaries else 0
        logger.info('%s: Average: %.2f Number of people: %s', year, average, len(salaries))




def create_charts(names_list, yearly_salary_dict, yearly_chart_path, titles_chart_path):
    years_sorted = sorted(yearly_salary_dict.keys())
    averages = [sum(yearly_salary_dict[y]) / len(yearly_salary_dict[y]) for y in years_sorted]
    counts   = [len(yearly_salary_dict[y]) for y in years_sorted]

    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax1.bar(years_sorted, counts, color='steelblue', alpha=0.4, label='# of People')
    ax1.set_ylabel('Number of People', color='steelblue')
    ax1.tick_params(axis='x', rotation=45)

    ax2 = ax1.twinx()
    ax2.plot(years_sorted, averages, color='crimson', marker='o', linewidth=2, label='Avg Salary')
    ax2.set_ylabel('Average Salary ($)', color='crimson')
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}'))

    plt.title('Ontario Sunshine List — Average Salary & Headcount by Year')
    fig.tight_layout()
    try:
        fig.savefig(yearly_chart_path, dpi=150)
    finally:
        plt.close(fig)


    title_counts = Counter(p['Job Title'] for p in names_list if p['Job Title'])
    top_titles = title_counts.most_common(10)
    if not top_titles:
        logger.warning("No job titles available; title chart was not written")
        return
    labels, values = zip(*top_titles)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh(labels[::-1], values[::-1], color='teal')
    ax.set_xlabel('Number of Appearances')
    ax.set_title('Top 10 Most Common Job Titles on the Sunshine List')
    fig.tight_layout()
    try:
        fig.savefig(titles_chart_path, dpi=150)
    finally:
        plt.close(fig)
