import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from personal_context.episodes import EpisodeBuilder, LocalOllamaSummarizer, main
from personal_context.service import QueryService
from personal_context.store import Store


class EpisodeTests(unittest.TestCase):
    def test_backfill_continues_after_one_model_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "context.sqlite3"
            local = ZoneInfo("America/New_York")
            today = datetime.now(local).date()
            bad_day, good_day = today - timedelta(days=1), today - timedelta(days=2)
            def at_noon(day):
                return datetime.combine(day, time(hour=12), local).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            store = Store(db)
            store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                          "scope": "messages:test", "collected_at": datetime.now(timezone.utc).isoformat(),
                          "complete": True,
                          "records": [{"id": "bad", "title": "Bad", "body": "Synthetic",
                                       "start": at_noon(bad_day)},
                                      {"id": "good", "title": "Good", "body": "Synthetic",
                                       "start": at_noon(good_day)}]})
            store.close()
            def summarize(items):
                if items[0]["title"] == "Bad":
                    raise ValueError("invalid model output")
                return {"summary": "Good day summary", "citations": [items[0]["key"]]}
            with patch("personal_context.cli.require_archive_key"), \
                 patch("personal_context.episodes.LocalOllamaSummarizer", return_value=summarize), \
                 patch("sys.stdout", new_callable=io.StringIO):
                status = main(["--db", str(db), "--days", "2", "--timezone", "America/New_York"])
            self.assertEqual(1, status)
            store = Store(db)
            self.assertEqual([], store.episode_parts(bad_day.isoformat(), "America/New_York"))
            self.assertEqual(1, len(store.episode_parts(good_day.isoformat(), "America/New_York")))
            store.close()

    def test_local_model_maps_short_indices_to_exact_source_keys(self):
        answer = {"done": True, "response": json.dumps({"summary": "Discussed milestones.",
                                                       "citations": [0]})}
        with patch("personal_context.episodes.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(answer).encode())):
            result = LocalOllamaSummarizer()([{"key": "message:m1", "kind": "message",
                                               "title": "Discussion", "body": "Milestones",
                                               "at": "2026-09-30T16:00:00Z"}])
        self.assertEqual(["message:m1"], result["citations"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "context.sqlite3"
        self.store = Store(self.path)
        self.store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                           "scope": "messages:test", "collected_at": "2026-10-01T00:00:00Z",
                           "complete": True,
                           "records": [{"id": "m1", "title": "Project discussion",
                                        "body": "Discussed prototype milestones",
                                        "start": "2026-09-30T16:00:00Z"}]})

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_source_cited_episode_is_encrypted_store_data_and_skips_unchanged_input(self):
        calls = []
        def summarize(items):
            calls.append(items)
            return {"summary": "Discussed prototype milestones.",
                    "citations": ["message:m1"]}
        builder = EpisodeBuilder(self.store, summarize, model="synthetic", timezone_name="America/New_York")
        self.assertEqual(1, builder.sync_day("2026-09-30"))
        self.assertEqual(0, builder.sync_day("2026-09-30"))
        self.assertEqual(1, len(calls))
        result = QueryService(self.path).daily_summary("2026-09-30", "America/New_York")
        self.assertEqual("Discussed prototype milestones.", result["parts"][0]["summary"])
        self.assertEqual(["message:m1"], result["parts"][0]["citations"])
        self.assertTrue(result["generated_unverified"])

    def test_invalid_citation_cannot_replace_existing_episode(self):
        good = EpisodeBuilder(self.store, lambda items: {
            "summary": "Original summary", "citations": ["message:m1"]},
            model="synthetic", timezone_name="America/New_York")
        good.sync_day("2026-09-30")
        self.store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                           "scope": "messages:test", "collected_at": "2026-10-02T00:00:00Z",
                           "complete": True,
                           "records": [{"id": "m1", "title": "Project discussion",
                                        "body": "Changed source text",
                                        "start": "2026-09-30T16:00:00Z"}]})
        bad = EpisodeBuilder(self.store, lambda items: {
            "summary": "Invented", "citations": ["message:not-in-input"]},
            model="synthetic", timezone_name="America/New_York")
        with self.assertRaises(ValueError):
            bad.sync_day("2026-09-30")
        self.assertEqual("Original summary", self.store.episode_parts("2026-09-30", "America/New_York")[0]["summary"])

    def test_source_citations_can_cover_every_record_in_a_bounded_chunk(self):
        records = [{"id": "m" + str(index), "title": "Synthetic discussion",
                    "body": "Topic " + str(index), "start": "2026-09-30T16:00:00Z"}
                   for index in range(16)]
        self.store.ingest({"schema": 1, "source": "apple-local", "kind": "message",
                           "scope": "messages:test", "collected_at": "2026-10-02T00:00:00Z",
                           "complete": True, "records": records})
        builder = EpisodeBuilder(self.store, lambda items: {
            "summary": "Synthetic topics were discussed.",
            "citations": [item["key"] for item in items]}, model="synthetic")
        self.assertEqual(1, builder.sync_day("2026-09-30"))
        self.assertEqual(16, len(self.store.episode_parts("2026-09-30", builder.timezone_name)[0]["citations"]))

    def test_generator_and_reader_share_private_timezone_configuration(self):
        import os
        with patch.dict(os.environ, {"PERSONAL_CONTEXT_TIMEZONE": "Asia/Tokyo"}):
            builder = EpisodeBuilder(self.store, lambda items: {
                "summary": "Synthetic discussion", "citations": ["message:m1"]})
            builder.sync_day("2026-10-01")
            result = QueryService(self.path).daily_summary("2026-10-01")
            self.assertEqual("Asia/Tokyo", result["timezone"])
            self.assertEqual(1, len(result["parts"]))
            self.assertEqual("UTC", EpisodeBuilder(self.store, None, timezone_name="UTC").timezone_name)

    def test_timezone_defaults_to_utc_and_invalid_setting_fails(self):
        import os
        from personal_context.settings import configured_timezone
        from zoneinfo import ZoneInfoNotFoundError
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("UTC", configured_timezone())
        with patch.dict(os.environ, {"PERSONAL_CONTEXT_TIMEZONE": "Not/AZone"}):
            with self.assertRaises(ZoneInfoNotFoundError):
                EpisodeBuilder(self.store, None)
            with self.assertRaises(ZoneInfoNotFoundError):
                QueryService(self.path).daily_summary("2026-09-30")


if __name__ == "__main__":
    unittest.main()
