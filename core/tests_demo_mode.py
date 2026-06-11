from __future__ import annotations

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from core.demo_mode import is_demo_request


class DemoModeTests(SimpleTestCase):
    def test_demo_path_enables_demo_mode(self):
        factory = APIRequestFactory()
        request = factory.get("/demo/console")
        self.assertTrue(is_demo_request(request))

    def test_console_path_is_not_demo(self):
        factory = APIRequestFactory()
        request = factory.get("/console")
        self.assertFalse(is_demo_request(request))

    @override_settings(DEMO_HOSTS=["demo.example.com"], ALLOWED_HOSTS=["demo.example.com", "testserver"])
    def test_demo_host_enables_demo_mode(self):
        factory = APIRequestFactory()
        request = factory.get("/console", HTTP_HOST="demo.example.com")
        self.assertTrue(is_demo_request(request))
