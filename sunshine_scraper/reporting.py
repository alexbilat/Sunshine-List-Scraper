"""Report database aggregates; this module does not download, validate, or query."""
import logging
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)


def print_yearly_summary(yearly_summary):
    """Log an average and record count for each year, newest first.

    yearly_summary holds YearSummary aggregates computed by the database.
    """
    for summary in sorted(yearly_summary, key=summary_year, reverse=True):
        logger.info('%s: Average: %.2f Number of people: %s', summary.year,
                    summary.average_dollars, summary.people)


def summary_year(summary):
    """Give sorted the year each YearSummary should be ordered by."""
    return summary.year


def create_charts(yearly_summary, top_titles, yearly_chart_path, titles_chart_path):
    """Save yearly totals and the most frequent nonempty job titles.

    Inputs are aggregates from the database (YearSummary and TitleCount rows),
    so the charts never need every record in memory. File errors propagate to
    the pipeline, which can report failure while keeping the TSV.
    """
    # All three lists must use the same year order so each bar and point align.
    # Year labels are text so matplotlib draws one evenly spaced bar per year.
    ordered = sorted(yearly_summary, key=summary_year)
    years_sorted = [str(summary.year) for summary in ordered]
    averages = [summary.average_dollars for summary in ordered]
    counts = [summary.people for summary in ordered]

    figure, count_axis = plt.subplots(figsize=(14, 6))
    count_axis.bar(years_sorted, counts, color='steelblue', alpha=0.4, label='# of People')
    count_axis.set_ylabel('Number of People', color='steelblue')
    count_axis.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
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

    if not top_titles:
        logger.warning("No job titles available; title chart was not written")
        return  # Leave any previously saved title chart untouched.

    # The database returns largest first. Reverse the order so the largest bar
    # appears at the top of a horizontal chart, whose first bar is at the bottom.
    labels = [title.job_title for title in reversed(top_titles)]
    values = [title.appearances for title in reversed(top_titles)]

    figure, title_axis = plt.subplots(figsize=(12, 6))
    title_axis.barh(labels, values, color='teal')
    title_axis.set_xlabel('Number of Appearances')
    title_axis.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    title_axis.set_title('Top 10 Most Common Job Titles on the Sunshine List')
    figure.tight_layout()
    try:
        figure.savefig(titles_chart_path, dpi=150)
    finally:
        plt.close(figure)
