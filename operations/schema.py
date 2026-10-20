from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieOrHeaderJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "operations.authentication.CookieOrHeaderJWTAuthentication"
    name = "BearerAuth"
    priority = 1

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
