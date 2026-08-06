"""WSGI config for RestPOS."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restpos.settings")

application = get_wsgi_application()
