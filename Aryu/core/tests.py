import json
from django.test import TestCase, RequestFactory
from core.middleware.security_sanitizer import InputSanitizationMiddleware


class InputSanitizationMiddlewareTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = InputSanitizationMiddleware(lambda r: None)

    def test_resume_rich_text_html_preserved(self):
        """Test 1: Rich Text Editor HTML in resume builder experiences[].text is preserved."""
        quill_html = (
            '<ol>'
            '<li data-list="bullet">'
            '<span class="ql-ui" contenteditable="false"></span>'
            'Managed daily operational workflows to ensure alignment with organizational goals.'
            '</li>'
            '<li data-list="bullet">'
            '<span class="ql-ui" contenteditable="false"></span>'
            'Collaborated with cross-functional teams to identify operational bottlenecks.'
            '</li>'
            '</ol>'
        )
        payload = {
            "resume_title": "<b>Lead Engineer</b>",
            "resume_data": {
                "employer": "<strong>Global Tech Corp</strong>",
                "experiences": [
                    {
                        "employer": "<b>Acme Corp</b>",
                        "jobTitle": "<i>Senior Developer</i>",
                        "location": "<span>Remote</span>",
                        "text": quill_html,
                    }
                ]
            }
        }
        req = self.factory.post(
            "/api/resume/user-resumes",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)

        # Rich text is preserved
        self.assertEqual(
            processed["resume_data"]["experiences"][0]["text"],
            quill_html
        )
        # Normal fields have HTML stripped to plain text
        self.assertEqual(processed["resume_title"], "Lead Engineer")
        self.assertEqual(processed["resume_data"]["employer"], "Global Tech Corp")
        self.assertEqual(processed["resume_data"]["experiences"][0]["employer"], "Acme Corp")
        self.assertEqual(processed["resume_data"]["experiences"][0]["jobTitle"], "Senior Developer")
        self.assertEqual(processed["resume_data"]["experiences"][0]["location"], "Remote")

    def test_multiple_rich_text_list_items(self):
        """Test 2: Multiple list items in rich text are preserved."""
        list_html = "<ol><li>Item 1</li><li>Item 2</li></ol>"
        payload = {
            "experiences": [
                {
                    "text": list_html
                }
            ]
        }
        req = self.factory.post(
            "/api/resume/user-resumes",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["experiences"][0]["text"], list_html)

    def test_nested_experience_objects(self):
        """Test 3: Nested experience objects preserve HTML for multiple records."""
        payload = {
            "experiences": [
                {"text": "<p>Experience 1</p>", "employer": "<b>Employer 1</b>"},
                {"text": "<p>Experience 2</p>", "employer": "<i>Employer 2</i>"},
            ]
        }
        req = self.factory.post(
            "/api/resume/user-resumes",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["experiences"][0]["text"], "<p>Experience 1</p>")
        self.assertEqual(processed["experiences"][0]["employer"], "Employer 1")
        self.assertEqual(processed["experiences"][1]["text"], "<p>Experience 2</p>")
        self.assertEqual(processed["experiences"][1]["employer"], "Employer 2")

    def test_normal_text_cleaned_in_resume_api(self):
        """Test 4: Normal non-rich-text fields in resume API have HTML stripped."""
        payload = {
            "resume_title": "<h1>My Title</h1>",
            "section_name": "<b>experiences</b>",
            "section_payload": [
                {
                    "employer": "<strong>Tech Labs</strong>",
                    "jobTitle": "<em>Lead</em>",
                    "text": "<p>Valid rich text</p>",
                }
            ]
        }
        req = self.factory.patch(
            "/api/resume/user-resumes/1",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["resume_title"], "My Title")
        self.assertEqual(processed["section_name"], "experiences")
        self.assertEqual(processed["section_payload"][0]["employer"], "Tech Labs")
        self.assertEqual(processed["section_payload"][0]["jobTitle"], "Lead")
        self.assertEqual(processed["section_payload"][0]["text"], "<p>Valid rich text</p>")

    def test_unrelated_resume_endpoints_clean_html(self):
        """Test 5: HTML in unrelated resume endpoints (signup, contact) is cleaned."""
        payload = {
            "first_name": "<b>Jane</b>",
            "last_name": "<i>Doe</i>",
            "message": "<p>Inquiry message</p>",
            "city": "<u>New York</u>",
        }
        req = self.factory.post(
            "/api/resume/contact",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["first_name"], "Jane")
        self.assertEqual(processed["last_name"], "Doe")
        self.assertEqual(processed["message"], "Inquiry message")
        self.assertEqual(processed["city"], "New York")

    def test_other_apps_remain_unchanged(self):
        """Test 6: Middleware sanitizes HTML to plain text in other non-resume apps."""
        payload = {
            "message": "<p>Hello <b>chat</b></p>",
            "text": "<div>Some chat text</div>",
            "description": "<i>Channel description</i>",
        }
        req = self.factory.post(
            "/api/chats/messages",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["message"], "Hello chat")
        self.assertEqual(processed["text"], "Some chat text")
        self.assertEqual(processed["description"], "Channel description")

    def test_deeply_nested_rich_text_fields(self):
        """Test 7: Arbitrarily nested rich text structures preserve HTML."""
        payload = {
            "profile": {
                "name": "<b>Alice</b>",
                "experiences": [
                    {
                        "company": "<i>Initech</i>",
                        "text": "<p>Building <strong>distributed systems</strong>.</p>",
                    }
                ]
            }
        }
        req = self.factory.post(
            "/api/resume/user-resumes",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        self.assertEqual(processed["profile"]["name"], "Alice")
        self.assertEqual(processed["profile"]["experiences"][0]["company"], "Initech")
        self.assertEqual(
            processed["profile"]["experiences"][0]["text"],
            "<p>Building <strong>distributed systems</strong>.</p>"
        )

    def test_xss_vectors_sanitized_in_rich_text(self):
        """Test 8: XSS attack vectors are sanitized while safe tags are preserved."""
        malicious = (
            "<script>alert('XSS')</script>"
            "<p>Safe text with <a href=\"javascript:alert('bad')\">Bad Link</a> "
            "and <a href=\"https://example.com\" target=\"_blank\">Good Link</a> "
            "and <img src=\"x\" onerror=\"alert(1)\">.</p>"
        )
        payload = {
            "experiences": [
                {
                    "text": malicious
                }
            ]
        }
        req = self.factory.post(
            "/api/resume/user-resumes",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.middleware.process_request(req)
        processed = json.loads(req.body)
        sanitized_text = processed["experiences"][0]["text"]
        self.assertNotIn("<script>", sanitized_text)
        self.assertNotIn("javascript:", sanitized_text)
        self.assertNotIn("onerror", sanitized_text)
        self.assertIn('<a href="https://example.com" target="_blank">Good Link</a>', sanitized_text)
        self.assertIn("<p>Safe text with <a>Bad Link</a>", sanitized_text)
