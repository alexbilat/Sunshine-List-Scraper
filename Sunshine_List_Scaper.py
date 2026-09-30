"""Command-line entry point (original filename retained for compatibility)."""
import sys
import config
from sunshine_scraper.pipeline import run


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        run(config.url, config.api_url, config.output_path,
            config.yearly_chart_path, config.titles_chart_path)
    except (RuntimeError, FileNotFoundError) as error:
        print(error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
