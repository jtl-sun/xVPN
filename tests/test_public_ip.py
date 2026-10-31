"""Offline tests: IP lookup uses no live network access."""
import io
import json
import unittest
from unittest.mock import patch
import urllib.error
from xvpn.backend import VPNBackend, VPNError


class Reply:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.value).encode('utf-8')


class PublicIPTests(unittest.TestCase):
    def test_primary_success_does_not_call_fallback(self):
        result = Reply({'ip':'203.0.113.11','country_name':'Japan','city':'Tokyo'})
        with patch('xvpn.backend.urllib.request.urlopen', return_value=result) as fetch:
            value = VPNBackend().public_ip()
        self.assertEqual(value['source'], 'ipapi.co')
        self.assertEqual(value['country'], 'Japan')
        self.assertEqual(fetch.call_count, 1)

    def test_rate_limit_falls_back_to_geojs(self):
        limited = urllib.error.HTTPError('https://ipapi.co/json/', 429, 'Too Many Requests', {}, io.BytesIO())
        reply = Reply({'ip':'198.51.100.22','country':'South Korea','city':'Seoul'})
        with patch('xvpn.backend.urllib.request.urlopen', side_effect=[limited, reply]) as fetch:
            result = VPNBackend().public_ip()
        self.assertEqual(result['source'], 'GeoJS')
        self.assertEqual(result['country'], 'South Korea')
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('get.geojs.io', fetch.call_args.args[0].full_url)

    def test_bad_json_response_falls_back(self):
        a = Reply({'error':True, 'reason':'RateLimited'})
        b = Reply({'ip':'192.0.2.10','country':'United States','city':'New York'})
        with patch('xvpn.backend.urllib.request.urlopen', side_effect=[a,b]):
            self.assertEqual(VPNBackend().public_ip()['source'], 'GeoJS')

    def test_both_providers_unavailable_has_friendly_error(self):
        error = urllib.error.HTTPError('https://example.org/', 429, 'Too Many Requests', {}, io.BytesIO())
        with patch('xvpn.backend.urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(VPNError, 'does not mean Proton VPN has disconnected'):
                VPNBackend().public_ip()

    def test_invalid_ip_not_reported_as_success(self):
        with patch('xvpn.backend.urllib.request.urlopen', side_effect=[Reply({'ip':'not-an-ip'}), Reply({'ip':None})]):
            with self.assertRaises(VPNError):
                VPNBackend().public_ip()


if __name__ == '__main__':
    unittest.main()
