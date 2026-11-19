"""
Admin registration for the tour app
"""

# Third-party imports (Django)
from django.contrib import admin

# Local imports
from .models import TourSeen

admin.site.register(TourSeen)
