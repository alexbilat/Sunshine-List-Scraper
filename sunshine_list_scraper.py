"""CLI entry point: configure logging and translate failures to exit codes."""
import logging
import sys
import config
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.pipeline import run
from sunshine_scraper.storage.connection import DatabaseAccessError, DatabaseConfigurationError
from sunshine_scraper.storage.migrations import MigrationError

logger = logging.getLogger(__name__)


def main():
    """Return 0 for success, 1 for failure, or 130 for a user interruption."""
    # Configure logging once at startup. Each module supplies its own logger name.
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        # Keep a default INFO handler even if the configured level is invalid.
        logging.getLogger().setLevel(config.log_level)
        # Some captured output streams cannot change encoding.
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        complete = run(config.url, config.api_url, config.output_path,
            config.yearly_chart_path, config.titles_chart_path,
            timeout=config.request_timeout, max_retries=config.max_retries,
            backoff=config.retry_backoff, full_refresh=config.full_refresh)
        if complete:
            return 0
        return 1
    except (ScraperError, OSError, DatabaseConfigurationError, DatabaseAccessError,
            MigrationError) as error:
        # Expected request/data, file, and database failures get a concise
        # message. Database messages never include the connection URL.
        logger.error("Scraper stopped: %s", error)
        return 1
    except KeyboardInterrupt:
        # Ctrl+C is an intentional interruption, not a programming bug.
        logger.warning("Scraper interrupted by user")
        return 130
    except Exception:
        # Last-resort CLI boundary: preserve the traceback for debugging.
        logger.exception("Unexpected failure; scraper stopped")
        return 1


# Importing this file does not run the scraper. Direct execution does.
# SystemExit passes main's result to the shell as the process exit code.
if __name__ == '__main__':
    raise SystemExit(main())
