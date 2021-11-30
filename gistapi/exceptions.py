from werkzeug.exceptions import HTTPException


class APIError(HTTPException):
    code = 500


class GistError(APIError):
    def __str__(self):
        return f'Github gists error: {self.description}'


class ValidationError(APIError):
    code = 400
