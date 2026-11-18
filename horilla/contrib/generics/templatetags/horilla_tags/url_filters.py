"""Template filters for URL manipulation."""

# Standard library imports
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Local imports
from ._registry import register


@register.filter
def concat(value, arg):
    """Join two values as text.

    On a reports template ``add`` comes from ``reports_tags`` and only adds
    numbers. A path plus ``?total=`` is not a number, so that ``add`` returns
    the path and the query is lost. Use ``concat`` to append text.
    """
    left = "" if value is None else value
    right = "" if arg is None else arg
    return f"{left}{right}"


@register.filter
def remove_query_param(url, param):
    """
    Removes a query parameter from a URL string.
    Example: {{ request.get_full_path|remove_query_param:"section" }}
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params.pop(param, None)
    new_query = urlencode(query_params, doseq=True)
    cleaned_url = urlunparse(parsed_url._replace(query=new_query))
    return cleaned_url
