"""Aggregate view modules for the `core.views` package."""

from horilla.contrib.core.views.core import (
    HomePageView,
    ReloadMessages,
    ClearRecentlyViewedView,
    SaveActiveTabView,
    LoginUserView,
    LogoutView,
    SettingView,
    SettingsSearchView,
    MySettingView,
    SwitchCompanyView,
    ToggleAllCompaniesView,
    CompanyDetailsTab,
    GetCountrySubdivisionsView,
    FaviconRedirectView,
    protected_media,
)

from horilla.contrib.core.views.branches import (
    BranchesView,
    BranchNavbar,
    BranchListView,
    BranchDetailView,
    BranchDetailNavbar,
    BranchDetailContent,
    BranchDeleteView,
    CompanyInformationTabView,
    CompanyInformationView,
    CompanyMultiFormView,
    CompanyFormView,
)

from horilla.contrib.core.views.fiscal_year import (
    CompanyFiscalYearTab,
    FiscalYearFormView,
    FiscalYearFieldsView,
    CalculateStartDateDayView,
    CalculateWeekStartDayView,
    FiscalYearCalendarPreviewView,
    FiscalYearCalendarView,
)

from horilla.contrib.core.views.multiple_currency import (
    CompanyMultipleCurrency,
    CurrencyNavbar,
    FetchExchangeRateView,
    CurrencyListView,
    ChangeDefaultCurrencyView,
    ChangeDefaultCurrencyFormView,
    AddCurrencyView,
    ConversionRateFormView,
    DatedConversionRateFormView,
    DatedCurrencyListView,
    DatedConversionRateEditView,
    DatedConversionRateDeleteView,
    CurrencyDeleteView,
)

from horilla.contrib.core.views.roles import (
    RolesView,
    AddRole,
    AddUserToRole,
    RoleUsersListView,
    UsersInRoleView,
    DeleteUserFromRole,
    RoleDeleteView,
    RoleNavbar,
    RolesHierarchyView,
    RoleListView,
)

from horilla.contrib.core.views.departments import (
    DepartmentView,
    DepartmentNavbar,
    DepartmentListView,
    DepartmentFormView,
    DepartmentDeleteView,
)

from horilla.contrib.core.views.customer_role import (
    CustomerRoleView,
    CustomerRoleNavbar,
    CustomerRoleListView,
    CustomerRoleFormView,
    CustomerRoleDeleteView,
)

from horilla.contrib.core.views.export_data import (
    ExportView,
    ExportScheduleModalView,
    ExportScheduleCreateView,
    ScheduleExportListView,
    ScheduleExportDeleteView,
    ScheduleExportDetailView,
)

from horilla.contrib.core.views.groups_and_permissions import (
    ModelFieldsModalView,
    SaveBulkFieldPermissionsView,
    UpdateFieldPermissionView,
    SaveAllFieldPermissionsView,
    RolePermissionView,
    RolePermissionTabView,
    GroupTab,
    RolePermissionsView,
    SearchRoleModelsView,
    SearchUserModelsView,
    SearchAssignModelsView,
    RoleMembersView,
    PermissionTab,
    UpdateUserPermissionsView,
    LoadUserPermissionsView,
    LoadMoreUsersView,
    UpdateRolePermissionsView,
    AssignUsersView,
    UpdateRoleModelPermissionsView,
    UpdateRoleAllPermissionsView,
    UpdateUserModelPermissionsView,
    UpdateUserAllPermissionsView,
    BulkUpdateUserModelPermissionsView,
    BulkUpdateUserAllPermissionsView,
    SuperUserView,
    SuperUserNavbar,
    SuperUserTab,
    ToggleSuperuserView,
    AddSuperUsersView,
)

from horilla.contrib.core.views.import_data import (
    ImportView,
    ImportNavbar,
    ImportTabView,
    ImportDataView,
    ImportStep1View,
    ImportStep2View,
    ImportStep3View,
    ImportStep4View,
    GetModelFieldsView,
    UpdateFieldStatusView,
    GetUniqueValuesView,
    UpdateValueMappingStatusView,
    DownloadErrorFileView,
    ImportHistoryView,
    DownloadImportedFileView,
    DownloadTemplateModalView,
    DownloadTemplateView,
)

from horilla.contrib.core.views.initialiaze_database import (
    InitializeDatabaseConditionView,
    InitializeDatabase,
    InitializeDatabaseUser,
    InitializeDatabaseCompany,
    SignUpFormView,
    InitializeCompanyFormView,
    InitializeRoleView,
    InitializeDatabaseGoHomeView,
)

from horilla.contrib.core.views.load_data import (
    LoadDatabaseConditionView,
    LoadDatabase,
    ConfigureDemoData,
    LoadDemoDatabase,
)

from horilla.contrib.core.views.partner_role import (
    PartnerRoleView,
    PartnerRoleNavbar,
    PartnerRoleListView,
    PartnerRoleFormView,
    PartnerRoleDeleteView,
)

from horilla.contrib.core.views.recycle_bin import (
    RecycleBinView,
    RecycleBinNavbar,
    RecycleBinListView,
    RecycleDeleteView,
    BulkDeleteRecycleBinView,
    RecycleRestoreView,
    BulkRestoreRecycleView,
    EmptyRecycleBinView,
    BinPolicyView,
)

from horilla.contrib.core.views.user_holidays import (
    UserHolidayView,
    UserHolidayNavbar,
    UserHolidayListView,
    UserHolidayDetailView,
)

from horilla.contrib.core.views.regional_formating import ReginalFormatingView

from horilla.contrib.core.views.team_role import (
    TeamRoleView,
    TeamRoleNavbar,
    TeamRoleListView,
    TeamRoleFormView,
    TeamRoleDeleteView,
)

from horilla.contrib.core.views.user_login_history import (
    UserLoginHistoryView,
    UserLoginHistoryNavbar,
    UserloginHistoryListView,
)

from horilla.contrib.core.views.users import (
    UserView,
    UserNavbar,
    UserListView,
    UserKanbanView,
    UserGroupByView,
    UserFormView,
    GetCompanyRelatedFieldsView,
    ChangeUserCompanyView,
    UserFormViewSingle,
    UserDeleteView,
    UserDetailView,
    UserDetailNavbar,
    UserDetailTabView,
    UserDetailsTab,
    UserLoginHistoryTab,
    MyProfileView,
    LoginHistoryView,
    LoginHistoryNavbar,
    LoginHistoryListView,
)

from horilla.contrib.core.views.version_info import VersionInfotemplateView

from horilla.contrib.core.views.change_password import (
    ChangePasswordView,
    ChangePasswordFormView,
)

from horilla.contrib.core.views.forgot_password import (
    ForgotPasswordView,
    PasswordResetConfirmView,
)

from horilla.contrib.core.views.business_hour import (
    BusinessHourView,
    BusinessHourCardView,
    BusinessHourFormView,
    BusinessHourAddHolidayView,
    BusinessHourHolidayListView,
    BusinessHourHolidayModalView,
    BusinessHourHolidayRemoveView,
    BusinessHourHolidayReadonlyDetailView,
)
from horilla.contrib.core.views.shift_hour import (
    ShiftHourListView,
    ShiftHourFormView,
    ShiftHourDeleteView,
    ShiftHourDetailView,
)

from horilla.contrib.core.views.holiday import (
    HolidayView,
    HolidayNavbar,
    HolidayListView,
    HolidayFormView,
    HolidayDeleteView,
    HolidayDetailView,
)

__all__ = [
    # core.py
    "protected_media",
    "HomePageView",
    "ReloadMessages",
    "SaveActiveTabView",
    "LoginUserView",
    "LogoutView",
    "SettingView",
    "SettingsSearchView",
    "MySettingView",
    "SwitchCompanyView",
    "ToggleAllCompaniesView",
    "CompanyDetailsTab",
    "GetCountrySubdivisionsView",
    "FaviconRedirectView",
    # branches.py
    "BranchesView",
    "BranchNavbar",
    "BranchListView",
    "BranchDetailView",
    "BranchDetailNavbar",
    "BranchDetailContent",
    "BranchDeleteView",
    "CompanyInformationTabView",
    "CompanyInformationView",
    "CompanyMultiFormView",
    "CompanyFormView",
    # fiscal_year.py
    "CompanyFiscalYearTab",
    "FiscalYearFormView",
    "FiscalYearFieldsView",
    "CalculateStartDateDayView",
    "CalculateWeekStartDayView",
    "FiscalYearCalendarPreviewView",
    "FiscalYearCalendarView",
    # multiple_currency.py
    "CompanyMultipleCurrency",
    "CurrencyNavbar",
    "FetchExchangeRateView",
    "CurrencyListView",
    "ChangeDefaultCurrencyView",
    "ChangeDefaultCurrencyFormView",
    "AddCurrencyView",
    "ConversionRateFormView",
    "DatedConversionRateFormView",
    "DatedCurrencyListView",
    "DatedConversionRateEditView",
    "DatedConversionRateDeleteView",
    "CurrencyDeleteView",
    # roles.py
    "RolesView",
    "AddRole",
    "AddUserToRole",
    "RoleUsersListView",
    "UsersInRoleView",
    "DeleteUserFromRole",
    "RoleDeleteView",
    "RoleNavbar",
    "RolesHierarchyView",
    "RoleListView",
    # departments.py
    "DepartmentView",
    "DepartmentNavbar",
    "DepartmentListView",
    "DepartmentFormView",
    "DepartmentDeleteView",
    # customer_role.py
    "CustomerRoleView",
    "CustomerRoleNavbar",
    "CustomerRoleListView",
    "CustomerRoleFormView",
    "CustomerRoleDeleteView",
    # export_data.py
    "ExportView",
    "ExportScheduleModalView",
    "ExportScheduleCreateView",
    "ScheduleExportListView",
    "ScheduleExportDeleteView",
    "ScheduleExportDetailView",
    # groups_and_permissions.py
    "ModelFieldsModalView",
    "SaveBulkFieldPermissionsView",
    "UpdateFieldPermissionView",
    "SaveAllFieldPermissionsView",
    "RolePermissionView",
    "RolePermissionTabView",
    "GroupTab",
    "RolePermissionsView",
    "SearchRoleModelsView",
    "SearchUserModelsView",
    "SearchAssignModelsView",
    "RoleMembersView",
    "PermissionTab",
    "UpdateUserPermissionsView",
    "LoadUserPermissionsView",
    "LoadMoreUsersView",
    "UpdateRolePermissionsView",
    "AssignUsersView",
    "UpdateRoleModelPermissionsView",
    "UpdateRoleAllPermissionsView",
    "UpdateUserModelPermissionsView",
    "UpdateUserAllPermissionsView",
    "BulkUpdateUserModelPermissionsView",
    "BulkUpdateUserAllPermissionsView",
    "SuperUserView",
    "SuperUserNavbar",
    "SuperUserTab",
    "ToggleSuperuserView",
    "AddSuperUsersView",
    # import_data.py
    "ImportView",
    "ImportNavbar",
    "ImportTabView",
    "ImportDataView",
    "ImportStep1View",
    "ImportStep2View",
    "ImportStep3View",
    "ImportStep4View",
    "GetModelFieldsView",
    "UpdateFieldStatusView",
    "GetUniqueValuesView",
    "UpdateValueMappingStatusView",
    "DownloadErrorFileView",
    "ImportHistoryView",
    "DownloadImportedFileView",
    "DownloadTemplateModalView",
    "DownloadTemplateView",
    # initialiaze_database.py
    "InitializeDatabaseConditionView",
    "InitializeDatabase",
    "InitializeDatabaseUser",
    "InitializeDatabaseCompany",
    "SignUpFormView",
    "InitializeCompanyFormView",
    "InitializeRoleView",
    "InitializeDatabaseGoHomeView",
    # load_data.py
    "LoadDatabaseConditionView",
    "LoadDatabase",
    "ConfigureDemoData",
    "LoadDemoDatabase",
    # partner_role.py
    "PartnerRoleView",
    "PartnerRoleNavbar",
    "PartnerRoleListView",
    "PartnerRoleFormView",
    "PartnerRoleDeleteView",
    # recycle_bin.py
    "RecycleBinView",
    "RecycleBinNavbar",
    "RecycleBinListView",
    "RecycleDeleteView",
    "BulkDeleteRecycleBinView",
    "RecycleRestoreView",
    "BulkRestoreRecycleView",
    "EmptyRecycleBinView",
    "BinPolicyView",
    # user_holidays.py
    "UserHolidayView",
    "UserHolidayNavbar",
    "UserHolidayListView",
    "UserHolidayDetailView",
    # regional_formating.py
    "ReginalFormatingView",
    # team_role.py
    "TeamRoleView",
    "TeamRoleNavbar",
    "TeamRoleListView",
    "TeamRoleFormView",
    "TeamRoleDeleteView",
    # user_login_history.py
    "UserLoginHistoryView",
    "UserLoginHistoryNavbar",
    "UserloginHistoryListView",
    # users.py
    "UserView",
    "UserNavbar",
    "UserListView",
    "UserKanbanView",
    "UserGroupByView",
    "UserFormView",
    "GetCompanyRelatedFieldsView",
    "ChangeUserCompanyView",
    "UserFormViewSingle",
    "UserDeleteView",
    "UserDetailView",
    "UserDetailNavbar",
    "UserDetailTabView",
    "UserDetailsTab",
    "UserLoginHistoryTab",
    "MyProfileView",
    "LoginHistoryView",
    "LoginHistoryNavbar",
    "LoginHistoryListView",
    # version_info.py
    "VersionInfotemplateView",
    # change_password.py
    "ChangePasswordView",
    "ChangePasswordFormView",
    # forgot_password.py
    "ForgotPasswordView",
    "PasswordResetConfirmView",
    # business_hour.py
    "BusinessHourView",
    "BusinessHourCardView",
    "BusinessHourFormView",
    "BusinessHourAddHolidayView",
    "BusinessHourHolidayListView",
    "BusinessHourHolidayModalView",
    "BusinessHourHolidayRemoveView",
    # shift_hour.py
    "ShiftHourListView",
    "ShiftHourFormView",
    "ShiftHourDeleteView",
    "ShiftHourDetailView",
    # holiday.py
    "HolidayView",
    "HolidayNavbar",
    "HolidayListView",
    "HolidayFormView",
    "HolidayDeleteView",
    "HolidayDetailView",
]
