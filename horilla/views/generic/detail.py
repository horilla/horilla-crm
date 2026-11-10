"""Details view classes for all Horilla views."""

from django.views.generic import DetailView as DjangoDetailView

from horilla.views.generic.base import View


class DetailView(View, DjangoDetailView):
    """
    Django DetailView base for Horilla records detail screens.

    Inherits ``View``'s ``as_view()``, so ``_inherit_view`` extensions
    (``horilla.extension.view``) resolve for the concrete subclass on each
    request, the same mechanism already used by ``TemplateView`` and
    ``FormView``. Previously this class subclassed Django's ``DetailView``
    directly, so views built on it (for example the Activity tab,
    ``horilla.contrib.activity.views.core.HorillaActivitySectionView``)
    could not be extended without editing their source.
    """
