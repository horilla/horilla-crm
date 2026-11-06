# Opportunity Teams — Team Selling (`horilla_crm.opportunities.views.opportunity_team`)

## What this module does

Provides the **Team Selling** feature for opportunities: create named teams, assign default members with roles and access levels, then attach teams or individual members to individual opportunities.

---

## Feature flag: `TeamSellingRequiredMixin`

All team-selling views inherit this mixin. It gates access behind a runtime feature flag:

```python
class TeamSellingRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not team_selling_is_enabled():
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("opportunities:team_selling_setup")
                return response
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)
```

- **HTMX requests** → 204 + `HX-Redirect` header pointing at the setup page.
- **Non-HTMX requests** → HTTP 403.

The setup page (`TeamSellingSetupView`) and `ToggleTeamSellingView` are exempt from this mixin so users can enable the feature.

Feature checks resolve through **`OpportunitySettings.is_team_selling_enabled`** (and related helpers), which load the company settings row via request-local cache then the [per-company settings cache](../../horilla/contrib/utils/company_settings_cache.md) (`CACHE_NAMESPACE = "opportunities.settings"`). Invalidate on `save` / `delete` / create.

---

## View inventory

### Team management

| View | Base | Purpose |
|------|------|---------|
| `OpportunityTeamView` | `HorillaView` | Main section shell — [My Settings list shell](../../horilla/contrib/core/settings_list_shell.md#my-settings-list-shell-my_settings_list_shellhtml) (`my_settings_list_shell.html`) |
| `OpportunityTeamNavbar` | `HorillaNavView` | Navigation with "Create Team" action |
| `OpportunityTeamListView` | `HorillaListView` | Owner-filtered list of teams |
| `OpportunityTeamFormView` | `HorillaSingleFormView` | Create/update team; condition rows for bulk member add |
| `OpportunityTeamDetailView` | `DetailView` | Team detail page |
| `OpportunityTeamDetailNavbar` | `HorillaNavView` | Detail page navigation |
| `OpportunityTeamDetailListView` | `HorillaListView` | List of default members for a team |
| `OpportunityTeamDeleteView` | `HorillaSingleDeleteView` | Delete team |

### Member management

| View | Base | Purpose |
|------|------|---------|
| `OpportunityTeamMemberCreateView` | `HorillaSingleFormView` | Add one or more default members via condition rows |
| `OpportunityTeamMemberUpdateView` | `HorillaSingleFormView` | Edit role/access level for a default member |
| `OpportunityTeamMembersDeleteView` | `HorillaSingleDeleteView` | Remove a default member from a team |

### Opportunity-level team assignment

| View | Base | Purpose |
|------|------|---------|
| `AddDefaultTeamView` | `HorillaSingleFormView` | Attach a named team (with its default members) to an opportunity |
| `AddOpportunityMemberView` | `HorillaSingleFormView` | Add individual members directly to an opportunity |
| `OpportunityMemberUpdateView` | `HorillaSingleFormView` | Update a member's role on an opportunity |
| `OpportunityMembersDeleteView` | `HorillaSingleDeleteView` | Remove a member; checks for `OpportunitySplit` before deletion |

### Feature control

| View | Base | Purpose |
|------|------|---------|
| `TeamSellingSetupView` | `TemplateView` | Onboarding / setup page shown when feature is disabled |
| `ToggleTeamSellingView` | `View` | Enable or disable the team selling feature flag |

---

## Key patterns

### Condition rows for bulk member creation

`OpportunityTeamMemberCreateView` sets `condition_fields = ["user", "team_role", "opportunity_access_level"]` with `condition_model = None`. Each non-empty condition row produces one `OpportunityTeamMember` instance. Duplicate detection checks the `(user, team)` pair within the same submit.

### Who can use Team Selling

`OpportunitySettings` stores `team_selling_access_type` plus allowed roles and users: all users, specific roles, or specific users. `user_can_use_team_selling` is what `TeamSellingRequiredMixin` and the My Settings entry check, so a user outside that set does not see or open the team views. The setup page is a Team Selling card (toggle and status) and an Access Control card. The Opportunity Split enable toggle uses the same card.

`OpportunitySplit.OWNER_FIELDS` is `["user"]`, so a user with only `view_own_opportunitysplit` sees their own splits in lists and reports.

### Ownership and permissions (Team Selling)

Team-selling views do **not** require blanket `add_opportunityteammember` /
`change_opportunityteammember` (etc.) admin grants for day-to-day use:

- Any user can create, edit, and delete **their own** Opportunity Team and its
  default members (`OpportunityTeamFormView`, member create/update/delete, team
  delete) via ownership-aware `has_permission()` / `get_object()` overrides.
- On a specific opportunity, the owner (or anyone for whom
  `Opportunity.is_change_granted()` is true — role managers, edit/owner-level
  team access) can add a default team, add members, and update/remove members.
  Opportunity-level member views resolve access through the parent Opportunity
  because `OpportunityTeamMember` has no `OWNER_FIELDS` of its own.
- `OpportunityTeamListView` / `OpportunityTeamDetailListView` set
  `owner_filtration = False` and scope querysets themselves, so the generic
  view/view_own gate does not empty the list after a user creates their team.
- Related-list **Add Team** / **Add Members** buttons use the same
  `is_change_granted()` check so the UI matches who can submit those actions.

### Duplicate prevention

Both team-level and opportunity-level member views use `check_duplicate_instance` to prevent inserting the same user twice:

- Team members: unique on `(user, team)`.
- Opportunity members: unique on `(user, opportunity)`.

### OpportunitySplit guard on delete

`OpportunityMembersDeleteView.delete()` checks whether the member being removed has a linked `OpportunitySplit` row before proceeding. If a split exists, deletion is blocked and an error message is returned.

### URL param normalization

Some HTMX chains can produce malformed query strings (e.g. `?obj=3?obj=3`). Views that read an `obj` query param strip trailing `?…` fragments via `obj.split("?")[0].strip()` before using the value.

### `_thread_local` active company

`OpportunityTeamFormView` and `AddDefaultTeamView` fall back to `_thread_local.active_company` when the company is not set on the form instance. This handles the case where the middleware-populated thread local is the only available company reference during save.

---

## Related documentation

- [Opportunity stages](opportunity_stages.md)
- My Settings list shell: [../../horilla/contrib/core/settings_list_shell.md](../../horilla/contrib/core/settings_list_shell.md#my-settings-list-shell-my_settings_list_shellhtml)
- Empty-state partials (team-selling setup gate): [../../templates/components/empty_state.md](../../templates/components/empty_state.md)
- `HorillaSingleFormView` multi-instance example: [../../horilla/contrib/generics/views/single_form.md](../../horilla/contrib/generics/views/single_form.md)
- `HorillaListView`: [../../horilla/contrib/generics/views/list.md](../../horilla/contrib/generics/views/list.md)
- Four-layer permissions: [../../horilla/contrib/generics/mixins.md](../../horilla/contrib/generics/mixins.md)
