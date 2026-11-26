"""
This module defines the HorillaAttachment model,
"""

# Standard library imports
import logging
from html import unescape

from django.utils.html import strip_tags
from django.utils.text import Truncator

# First party imports (Horilla)
from horilla.contrib.utils.methods import sanitize_html, sanitize_plain_text
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.upload import upload_path

# Local imports
from .base import HorillaContentType, HorillaCoreModel

logger = logging.getLogger(__name__)


class HorillaAttachment(HorillaCoreModel):
    """
    Model representing a generic attachment in the Horilla system.

    This model allows attaching files or notes to any model instance using
    Django's GenericForeignKey mechanism.
    """

    title = models.CharField(max_length=255, verbose_name=_("Title"))
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Related Object Type"),
        help_text=_("The type of object this attachment is related to."),
    )
    object_id = models.PositiveIntegerField(
        verbose_name=_("Related Object ID"),
        help_text=_("The ID of the object this attachment is related to."),
    )
    related_object = models.GenericForeignKey("content_type", "object_id")
    file = models.FileField(
        _("File"),
        upload_to=upload_path,
        null=True,
        blank=True,
        help_text=_("Optional file attached to this record."),
    )
    description = models.TextField(
        _("Notes"),
        blank=True,
        null=True,
        help_text=_("Optional description or notes about the attachment."),
    )
    is_pinned = models.BooleanField(
        _("Pinned"),
        default=False,
        help_text=_("Pinned entries are shown first in the notes stream."),
    )

    class Meta:
        """
        Metadata for HorillaAttachment model.
        """

        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")

    @staticmethod
    def derive_title(description="", filename=""):
        """Title for an entry logged without one: first words of the note, else the file name."""
        text = " ".join(unescape(strip_tags(description or "")).split())
        if text:
            return Truncator(text).chars(60)
        return (filename or "").rsplit("/", 1)[-1]

    @property
    def show_title(self):
        """False when the title was auto-derived, so the stream does not repeat it."""
        derived = self.derive_title(
            self.description, self.file.name if self.file else ""
        )
        return self.title != derived

    @classmethod
    def history_create_label(cls, changes):
        """Wording for the History tab's creation entry: a note or an attachment."""
        values = (changes or {}).get("file")
        has_file = (
            isinstance(values, (list, tuple))
            and len(values) > 1
            and values[1] not in (None, "", "None")
        )
        return _("Attachment added") if has_file else _("Note added")

    @property
    def file_basename(self):
        """File name without its storage path."""
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    @property
    def is_image(self):
        """True when the attached file is an image the browser can preview."""
        return self.file_basename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
        )

    def history_source_col(self):
        """ "Related To" cell: Self for the listed record's own rows, else a link to the source record."""
        from horilla.contrib.generics.history import history_source_pill

        return history_source_pill(self)

    def clean(self):
        """Sanitize rich-text notes and plain-text title to prevent XSS."""
        if self.title:
            self.title = sanitize_plain_text(self.title)
        if self.description:
            self.description = sanitize_html(self.description)

    def save(self, *args, **kwargs):
        """Ensure clean() runs on every save path, including admin and API."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        """
        Returns a human-readable string representation of the attachment.
        """
        return str(self.title)

    def get_edit_url(self):
        """
        Returns the URL for editing this attachment.

        Returns:
            str: URL for the edit view of the attachment.
        """
        return reverse_lazy("generics:notes_attachment_edit", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        Returns the URL for deleting this attachment.

        Returns:
            str: URL for the delete view of the attachment.
        """
        return reverse_lazy("generics:notes_attachment_delete", kwargs={"pk": self.pk})
