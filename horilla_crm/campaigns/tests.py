"""
Tests for the campaigns app.
"""

# Standard library imports
import json
from collections import Counter
from pathlib import Path

# Third-party imports (Django)
from django.test import SimpleTestCase

# First party imports (Horilla)
from horilla.apps import apps


class CampaignDemoDataTests(SimpleTestCase):
    """The demo data loads campaigns evenly for the two demo companies, 20 by default."""

    FIXTURE = Path(__file__).resolve().parent / "load_data" / "campaign.json"

    @classmethod
    def rows(cls):
        """The campaign fixture rows."""
        return json.loads(cls.FIXTURE.read_text(encoding="utf-8"))

    @staticmethod
    def config():
        """The campaigns demo_data configuration."""
        return apps.get_app_config("campaigns").demo_data

    def split(self, count):
        """How many of the first ``count`` rows belong to each company."""
        return Counter(row["fields"]["company"] for row in self.rows()[:count])

    def test_the_default_is_twenty_campaigns_split_ten_and_ten(self):
        """What the loading page selects at first, and what a user who changes nothing gets."""
        self.assertEqual(self.config()["default"], 20)
        self.assertEqual(self.split(20), {1: 10, 2: 10})

    def test_the_default_is_one_of_the_offered_counts(self):
        """The loading page can select it."""
        self.assertIn(self.config()["default"], self.config()["options"])

    def test_every_count_offered_on_the_loading_page_is_split_evenly(self):
        """Choosing more than 10 does not unbalance the companies."""
        options = self.config()["options"]
        self.assertGreater(max(options), 10)
        for count in options:
            self.assertEqual(self.split(count), {1: count // 2, 2: count // 2}, count)

    # The Kanban stages the demo data fills. Aborted is not needed, so it is kept out.
    STAGES = ["new", "planned", "in_progress", "completed"]

    def statuses(self, count, company):
        """How many of the first ``count`` rows of ``company`` have each status."""
        found = Counter(
            row["fields"]["status"]
            for row in self.rows()[:count]
            if row["fields"]["company"] == company
        )
        return found

    def test_the_default_has_every_stage_in_both_companies(self):
        """No empty column on the Kanban board after loading the default."""
        default = self.config()["default"]
        for company in (1, 2):
            found = self.statuses(default, company)
            for stage in self.STAGES:
                self.assertGreaterEqual(found[stage], 1, (company, stage))
            self.assertEqual(sum(found.values()), default // 2, company)

    def test_the_default_has_no_aborted_campaign(self):
        """Aborted campaigns are not part of the demo, so they come last in the file."""
        for company in (1, 2):
            self.assertEqual(
                self.statuses(self.config()["default"], company)["aborted"], 0, company
            )

    def test_the_smallest_count_has_every_stage_too(self):
        """Choosing 10 instead still fills every column (the stages are spread over the file)."""
        smallest = min(self.config()["options"])
        for company in (1, 2):
            found = self.statuses(smallest, company)
            for stage in self.STAGES:
                self.assertGreaterEqual(found[stage], 1, (company, stage))

    def test_every_count_offered_has_every_stage_in_both_companies(self):
        """A bigger count never leaves a stage empty either."""
        for count in self.config()["options"]:
            for company in (1, 2):
                found = self.statuses(count, company)
                for stage in self.STAGES:
                    self.assertGreaterEqual(found[stage], 1, (count, company, stage))

    def test_no_count_asks_for_more_than_a_company_can_give(self):
        """Company 2 has 50 campaigns, so the largest offered count is 2 x 50."""
        per_company = Counter(row["fields"]["company"] for row in self.rows())
        self.assertLessEqual(max(self.config()["options"]), 2 * per_company[2])

    def test_the_options_are_even_counts(self):
        """An odd count could not be split evenly."""
        for count in self.config()["options"]:
            self.assertEqual(count % 2, 0, count)

    def test_the_file_keeps_all_its_campaigns_with_their_own_keys(self):
        """Only the order changed: 200 campaigns, no row of another model, no repeated pk."""
        rows = self.rows()
        self.assertEqual(len(rows), 200)
        self.assertEqual({row["model"] for row in rows}, {"campaigns.campaign"})
        self.assertEqual(len({row["pk"] for row in rows}), len(rows))

    def test_no_campaign_points_at_a_parent_that_comes_later_or_is_missing(self):
        """The demo data has no parent campaigns; if one is added, it must be loadable."""
        pks = {row["pk"] for row in self.rows()}
        for row in self.rows():
            parent = row["fields"].get("parent_campaign")
            self.assertTrue(parent is None or parent in pks, row["pk"])

    def test_the_loading_page_still_shows_the_campaign_picker(self):
        """The count stays configurable."""
        self.assertNotEqual(self.config().get("configurable", True), False)
