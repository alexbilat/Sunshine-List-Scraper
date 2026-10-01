"""CLI entry point: configure logging and translate failures to exit codes."""
import logging
import sys
import config
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.pipeline import run

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        logging.getLogger().setLevel(config.log_level)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        complete = run(config.url, config.api_url, config.output_path,
            config.yearly_chart_path, config.titles_chart_path,
            timeout=config.request_timeout, max_retries=config.max_retries,
            backoff=config.retry_backoff)
        return 0 if complete else 1
    except (ScraperError, OSError) as error:
        logger.error("Scraper stopped: %s", error)
        return 1
    except KeyboardInterrupt:
        logger.warning("Scraper interrupted by user")
        return 130
    except Exception:
        # Last-resort CLI boundary: preserve the traceback for debugging.
        logger.exception("Unexpected failure; scraper stopped")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
