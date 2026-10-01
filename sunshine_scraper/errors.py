"""Application-specific errors shared by the network layer and CLI."""


class ScraperError(Exception):
    """An expected failure that prevents a request or run from completing.

    Inheriting Exception gives this class normal Python exception behavior.
    Its distinct name lets the pipeline catch known scraper failures without
    catching unrelated bugs, while the CLI provides the final error message.
    """
