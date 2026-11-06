# Opportunity stages (`OpportunityStage`)

Pipeline stages for opportunities. Configured under **Settings → Opportunities → Stages** and during **Initialize Database** step 6.

---

## Default stages constant

**`DEFAULT_OPPORTUNITY_INIT_STAGES`** lives in `horilla_crm/opportunities/models.py`.

Each entry: `name`, `order`, `probability`, `is_final`. Standard sales pipeline from **Prospecting** through **Closed Won** / **Closed Lost** (10 stages).

### Where the constant is used

| Consumer | Purpose |
|----------|---------|
| `LoadOpportunityStagesView` | Init modal defaults and company signature grouping |
| `ensure_default_opportunity_stages_on_go_home` | Seed stages on [Go To Home](../../horilla/contrib/core/initialize_database.md) |
| Stage creation views | Reference the same probabilities and final flags |

Import:

```python
from horilla_crm.opportunities.models import (
    DEFAULT_OPPORTUNITY_INIT_STAGES,
    OpportunityStage,
)
```

When creating rows from the constant, map **`stage_type`** from probability:

| Probability | `stage_type` |
|-------------|--------------|
| `100` | `won` |
| `0` | `lost` |
| other | `open` |

The Go Home receiver (`_opportunity_stage_type` in `horilla_crm/opportunities/signals.py`) applies this mapping.

---

## Initialize Database flow

1. **`lead_stage_created`** with `initialization=True` renders the opportunity stages init screen.
2. User configures stages via `LoadOpportunityStagesView` / `CreateOppStageGroupView`.
3. On completion, navigation continues to home (or full wizard finish).

### Go To Home shortcut

**`initialize_database_go_home`** → `ensure_default_opportunity_stages_on_go_home` creates all default stages when the company has none. Skips if any `OpportunityStage` already exists.

---

## Settings UI

| View | Role |
|------|------|
| `OpportunityStageView` (in `opportunity_stages/base.py`) | [Settings list shell](../../horilla/contrib/core/settings_list_shell.md) |
| Navbar / list / form views | CRUD and ordering |

---

## Signals

| Signal | Module | Role |
|--------|--------|------|
| `opp_stage_created` | `horilla_crm/opportunities/signals.py` | Post-creation actions |
| `lead_stage_created` | `horilla_crm/leads/signals.py` | Chains from lead init to opportunity init |
| `initialize_database_go_home` | `horilla.contrib.core.signals` | Listener: `ensure_default_opportunity_stages_on_go_home` |

---

## Detail pipeline

`OpportunityDetailView` overrides `get_pipeline_choices()` to collapse Closed Won / Closed Lost into a single **Closed** pill (modal via `final_stage_action`).

| Layer | Behavior |
|-------|----------|
| `HorillaDetailView` | Dict pills + **`related_obj`** only; no CRM `is_final` handling. |
| `OpportunityDetailView` | Uses `_pipeline_choice(..., is_final=...)` so Closed / closed current stages open the closed-stage modal even when Closed Lost has `is_final=False` on the model. Open stages copy `related_obj.is_final` when set. |

Same generic/`related_obj` split as leads — see [lead stages](../leads/lead_stages.md#kanban--detail-pipeline) and [details.md](../../horilla/contrib/generics/views/details.md).

The closed-stage popup preselects **Closed Won**, unless the opportunity is already Closed Lost. The stage radios are not `required`; submitting with none selected shows "Please select Closed Won or Closed Lost." and does not send the request. The reply script is appended to `document.body`, so closing the modal does not interrupt the HTMX swap.

`email` is on both opportunity forms, after Amount.

---

## Related documentation

- [Opportunity team](opportunity_team.md)
- [Initialize Database](../../horilla/contrib/core/initialize_database.md)
- [Lead stages](../leads/lead_stages.md)
- [Detail generics](../../horilla/contrib/generics/views/details.md)
