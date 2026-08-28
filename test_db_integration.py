import sys
import unittest
from unittest.mock import patch, MagicMock
from src.telebot.db.workingna import get_admin_url
from src.telebot.db.tverkar import parse_salary_amount, map_gender, map_worker_status, upsert_worker_from_workingna
from src.telebot.core.migration import MigrationEngine

class TestDatabaseAndMigration(unittest.TestCase):
    def test_admin_url_generation(self):
        url = get_admin_url(1023058)
        self.assertEqual(url, "https://admin.workingna.com/cms/job-seeker/1023058?tab=detail")

    def test_salary_parsing(self):
        self.assertEqual(parse_salary_amount("$300"), 300.0)
        self.assertEqual(parse_salary_amount("500+"), 500.0)
        self.assertEqual(parse_salary_amount("២៥០$"), 250.0)
        self.assertEqual(parse_salary_amount("300-500"), 300.0)
        self.assertIsNone(parse_salary_amount(None))

    def test_gender_mapping(self):
        self.assertEqual(map_gender(1), "male")
        self.assertEqual(map_gender("1"), "male")
        self.assertEqual(map_gender(2), "female")
        self.assertEqual(map_gender("female"), "female")
        self.assertEqual(map_gender("ប្រុស"), "male")
        self.assertEqual(map_gender("ស្រី"), "female")

    def test_status_mapping(self):
        self.assertEqual(map_worker_status("ឈប់ហេីយ", "បន្ទាន់"), "urgent")
        self.assertEqual(map_worker_status("ឈប់ហេីយ", "កំពុងរកបណ្តេីរៗ"), "looking")
        self.assertEqual(map_worker_status("នៅធ្វេី", "ចង់"), "looking")
        self.assertEqual(map_worker_status("នៅធ្វេី", "មិនទាន់ចង់ទេ"), "employed")

    @patch("src.telebot.db.tverkar.get_tverkar_connection")
    def test_upsert_worker_from_workingna_mocked(self, mock_conn_fn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn_fn.return_value = mock_conn

        # Mock no existing worker found
        mock_cursor.fetchone.return_value = None

        sample_profile = {
            "profile_id": 1023058,
            "candidate_name": "Sophy Rakset",
            "raw_phone": "016202693",
            "e164_phone": "+85516202693",
            "gender": 1,
            "dob": "1998-05-15",
            "province": "Phnom Penh",
            "khan": "Tuol Kouk",
            "sangkat": "Tuek L'ak",
            "about_me": "Experienced Developer",
            "experiences": [
                {"company": "ABC Corp", "jobTitle": "Developer", "fromYear": 2022, "toYear": 2024}
            ],
            "educations": [
                {"school": "RUPP", "degree": "Bachelor", "fieldOfStudy": "Computer Science"}
            ]
        }
        survey_answers = {
            "employment_status": "នៅធ្វេី",
            "job_preference": "ចង់",
            "expected_salary": "$600",
            "preferred_location": "Phnom Penh"
        }
        tg_info = {"id": 1695796088, "username": "SofyRakset"}

        success, worker_id, err = upsert_worker_from_workingna(sample_profile, survey_answers, tg_info)
        self.assertTrue(success)
        self.assertIsNotNone(worker_id)
        self.assertIsNone(err)

    def test_google_sheets_payload_formatting(self):
        from src.telebot.integrations.google_sheets import format_row_for_sheet, GOOGLE_SHEET_COLUMNS
        raw_row = {
            "Index": 1,
            "Phone (E.164)": "+85587225303",
            "Candidate Name": "Sophy",
            "Workingna Admin URL": "https://admin.workingna.com/cms/job-seeker/1018015?tab=detail",
            "Extra Field": "ignored"
        }
        formatted = format_row_for_sheet(raw_row)
        self.assertEqual(len(formatted), len(GOOGLE_SHEET_COLUMNS))
        self.assertEqual(formatted["Index"], "1")
        self.assertEqual(formatted["Phone (E.164)"], "+85587225303")
        self.assertEqual(formatted["Candidate Name"], "Sophy")
        self.assertEqual(formatted["Workingna Admin URL"], "https://admin.workingna.com/cms/job-seeker/1018015?tab=detail")
        self.assertEqual(formatted["Consent Transfer"], "")

    @patch("requests.post")
    def test_google_sheets_sync_mock(self, mock_post):
        from src.telebot.integrations.google_sheets import sync_result_to_google_sheet_sync
        from src.telebot.config import config
        config.google_sheet_webhook_url = "https://script.google.com/macros/s/TEST/exec"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok, msg = sync_result_to_google_sheet_sync({"Index": 1, "Phone (E.164)": "+85587225303"})
        self.assertTrue(ok)
        self.assertEqual(msg, "Synced to Google Sheets")

if __name__ == "__main__":
    unittest.main()
