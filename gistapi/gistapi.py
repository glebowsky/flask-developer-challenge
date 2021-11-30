# coding=utf-8
"""
Exposes a simple HTTP API to search a users Gists via a regular expression.

Github provides the Gist service as a pastebin analog for sharing code and
other develpment artifacts.  See http://gist.github.com for details.  This
module implements a Flask server exposing two endpoints: a simple ping
endpoint to verify the server is up and responding and a search endpoint
providing a search across all public Gists for a given Github account.
"""
import json
import logging
import re
from typing import Iterable

import requests
from flask import Flask, jsonify, request

from exceptions import (
    APIError,
    GistError,
    ValidationError
)

logger = logging.getLogger(__name__)

# *The* app object
app = Flask(__name__)
app.config['TRAP_HTTP_EXCEPTIONS'] = True

GISTS_PAGE_LIMIT = 10


# Configuring exceptions handling
@app.errorhandler(APIError)
@app.errorhandler(ValidationError)
def handle_exception(e):
    return jsonify(status='error', message=str(e)), e.code


@app.route("/ping")
def ping():
    """Provide a static response to a simple GET request."""
    return "pong"


def get_gists_url(username) -> str:
    """
    Getting the initial gists page url
    """

    return f'https://api.github.com/users/{username}/gists?page=1&per_page={GISTS_PAGE_LIMIT}'


def _make_request(url: str):
    """
    Fetching data from the remote resource with the exceptions handling
    Handling some remove errors and raising them as GistError
    In the real environment I'd like to recommend using async python for
    Improving http fetching performance
    """
    response = requests.get(url)

    if not response.ok:
        error_obj = {}

        try:
            error_obj = response.json()
        except json.decoder.JSONDecodeError:
            pass

        raise GistError(error_obj.get('message'))

    return response


def gists_for_user(username: str) -> Iterable[dict]:
    """Provides the list of gist metadata for a given user.

    This abstracts the /users/:username/gist endpoint from the Github API.
    See https://developer.github.com/v3/gists/#list-a-users-gists for
    more information.

    Args:
        username (string): the user to query gists for
        page (int): current page

    Returns:
        The dict parsed from the json response from the Github API.  See
        the above URL for details of the expected structure.
    """

    next_page_url = get_gists_url(username)

    # BONUS: What failures could happen?
    #   - Temporary GitHub outage, unexpected errors should be handled
    #   - Github could block multiple requests for the short period of time.
    #       In this case we should add a delay or so
    #   - Some local connection issues
    #   - Timeout errors
    #   - Wrong user error
    # BONUS: Paging? How does this work for users with tons of gists?

    # I'd like to recommend creating Data Models for gist objects and files
    while next_page_url:
        response = _make_request(next_page_url)
        data = response.json()

        # Yielding values from the gists
        yield from data

        # Fetching next page url from the response header
        # If it does not exist, next page will be set as None
        # That will lead to the loop break
        try:
            next_page_url = response.links['next']['url']
        except KeyError:
            raise StopIteration


def regex_match(content, pattern) -> bool:
    """Searches pattern in provided content.
    Args:
        content(string): content to search
        pattern(string): Regular Expression
    Returns:
        Boolean status
    """
    return bool(re.match(pattern, content, re.MULTILINE))


def extract_gist_files_content(gist: dict) -> Iterable[str]:
    """
    Gist files content extractor
    """

    for file_obj in gist.get('files', {}).values():
        response = _make_request(file_obj['raw_url'])

        yield response.text


def build_gist_human_url(username: str, gist_id: str) -> str:
    """
    Building gist url for github web interface
    """

    return f'https://gist.github.com/{username}/{gist_id}'


def validate_username(username: str) -> str:
    """
    Primitive validation for username
    without using any extra serializer/form libraries
    """
    if not username:
        raise ValueError('Username field can not be empty')

    if not isinstance(username, str):
        raise ValueError('Invalid username type')

    return username.strip()


def validate_pattern(pattern: str) -> str:
    """
    Primitive validation for regex pattern
    without using any extra serializer/form libraries
    """

    if not pattern:
        raise ValueError('Pattern field can not be empty')

    try:
        re.compile(pattern)
    except Exception:
        raise ValueError("Invalid pattern")

    return pattern


@app.route("/api/v1/search", methods=['POST'])
def search():
    """Provides matches for a single pattern across a single users gists.

    Pulls down a list of all gists for a given user and then searches
    each gist for a given regular expression.

    Returns:
        A Flask Response object of type application/json.  The result
        object contains the list of matches along with a 'status' key
        indicating any failure conditions.
    """
    post_data = request.get_json()
    # [x] BONUS: Validate the arguments?

    try:
        username = validate_username(post_data.get('username'))
        pattern = validate_pattern(post_data.get('pattern'))
    except ValueError as exc:
        raise ValidationError(description=str(exc))

    result = {}
    matches = []
    gists = gists_for_user(username)
    # [x] BONUS: Handle invalid users?
    #   Handled in `_make_request` function

    # Using generalized exception handling for gists generator.
    # In case of specific handling for each operation we can use
    # while loop and itering through elements using iter() covered with try catch
    try:
        for gist in gists:
            # [x] REQUIRED: Fetch each gist and check for the pattern
            # [x] BONUS: What about huge gists?
            #   Case 1: Too much gist files
            #       Huge gists are indicated by `truncated: True` param.
            #       In this case github provides git_pull_url for cloning a gist
            #       to the local machine for further processing
            #   Case 2: Huge content of the individual file.
            #       In this case we should split this file
            #       and distribute it to the multiple workers/processes for parallel calculations.
            #       E.g use hadoop for distributed computing
            # [x] BONUS: Can we cache results in a datastore/db?
            #       Ideally we should use a permanent cache of file results of the gist
            #       with the cache name as the union of id + last edited date
            for content in extract_gist_files_content(gist):
                if regex_match(content, pattern):
                    matches.append(build_gist_human_url(username, gist['id']))

                    break
    except requests.RequestException:
        raise GistError('Something went wrong with the gist request')

    result['status'] = 'success'
    result['username'] = username
    result['pattern'] = pattern
    result['matches'] = matches

    return jsonify(result)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=9876)
