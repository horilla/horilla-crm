"""
Serializers for core models
"""

# Standard library imports
import copy

# Third-party imports (Django)
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

# First party imports (Horilla)
from horilla.api.mixins import CompanyScopedSerializerMixin
from horilla.auth.models import User
from horilla.core.exceptions import ValidationError

# Local imports
from ..models import (
    BusinessHour,
    Company,
    CustomerRole,
    Department,
    Holiday,
    HorillaAttachment,
    ImportHistory,
    PartnerRole,
    Role,
    TeamRole,
)


class CompanySerializer(serializers.ModelSerializer):
    """Serializer for Company model"""

    class Meta:
        """Meta class for CompanySerializer"""

        model = Company
        fields = "__all__"


class DepartmentSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Department model"""

    class Meta:
        """Meta class for DepartmentSerializer"""

        model = Department
        fields = "__all__"


class RoleSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Role model"""

    class Meta:
        """Meta class for RoleSerializer"""

        model = Role
        fields = "__all__"


class HorillaUserSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for HorillaUser model"""

    def validate(self, attrs):
        """Force ``company`` to the requester's company; superusers may choose one."""
        request = self.context.get("request")
        if request is not None and request.user.is_superuser:
            return super(CompanyScopedSerializerMixin, self).validate(attrs)
        return super().validate(attrs)

    class Meta:
        """Meta class for HorillaUserSerializer"""

        model = User
        fields = "__all__"
        # is_superuser/is_staff/user_permissions/groups must never be
        # settable through ordinary add_user/change_user permission --
        # the classic (non-DRF) user form already excludes these same
        # fields (horilla/contrib/core/forms/users.py UserFormClass.Meta.exclude)
        # so that granting someone "add user" or "change user" cannot be
        # used to mint or promote a superuser account.
        read_only_fields = [
            "is_superuser",
            "is_staff",
            "user_permissions",
            "groups",
            "last_login",
            "date_joined",
        ]
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        """Create and return a user with the given validated data."""
        password = validated_data.get("password")
        if password:
            try:
                validate_password(password)
            except ValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
        user = User.objects.create_user(**validated_data)
        return user

    def update(self, instance, validated_data):
        """Update user; set password via set_password if provided."""
        if "password" in validated_data:
            password = validated_data.pop("password")
            try:
                validate_password(password, user=instance)
            except ValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
            instance.set_password(password)
        return super().update(instance, validated_data)


class BusinessHourSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for BusinessHour model"""

    class Meta:
        """Meta class for BusinessHourSerializer"""

        model = BusinessHour
        fields = "__all__"


class TeamRoleSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for TeamRole model"""

    class Meta:
        """Meta class for TeamRoleSerializer"""

        model = TeamRole
        fields = "__all__"


class CustomerRoleSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for CustomerRole model"""

    class Meta:
        """Meta class for CustomerRoleSerializer"""

        model = CustomerRole
        fields = "__all__"


class PartnerRoleSerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for PartnerRole model"""

    class Meta:
        """Meta class for PartnerRoleSerializer"""

        model = PartnerRole
        fields = "__all__"


class ImportHistorySerializer(
    CompanyScopedSerializerMixin, serializers.ModelSerializer
):
    """Serializer for ImportHistory model"""

    class Meta:
        """Meta class for ImportHistorySerializer"""

        model = ImportHistory
        fields = "__all__"


class HorillaAttachmentSerializer(
    CompanyScopedSerializerMixin, serializers.ModelSerializer
):
    """Serializer for HorillaAttachment model"""

    class Meta:
        """Meta class for HorillaAttachmentSerializer"""

        model = HorillaAttachment
        fields = "__all__"


class HolidaySerializer(CompanyScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Holiday model"""

    class Meta:
        """Meta class for HolidaySerializer"""

        model = Holiday
        fields = "__all__"

    def validate(self, attrs):
        """
        Apply the holiday rules of ``Holiday.clean()`` and the dates rule for specific
        users, so bad data is a 400 with the field errors and not a server error when
        the model refuses to save it.
        """
        attrs = super().validate(attrs)
        holiday = copy.copy(self.instance) if self.instance else Holiday()
        for name, value in attrs.items():
            if name != "specific_users":
                setattr(holiday, name, value)
        try:
            holiday.clean()
        except ValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "error_dict") else exc.messages
            ) from exc

        if not holiday.all_users:
            users = attrs.get("specific_users")
            if users is None and self.instance:
                users = list(self.instance.specific_users.all())
            message = Holiday.clash_problem(
                holiday.company_id,
                holiday.start_date,
                holiday.end_date,
                all_users=False,
                user_ids=[user.pk for user in users or []],
                exclude_pk=holiday.pk,
            )
            if message:
                raise serializers.ValidationError({"start_date": [message]})
        return attrs
