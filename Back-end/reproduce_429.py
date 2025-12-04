
import unittest
from unittest.mock import MagicMock, patch
import requests
import sys
import os

# Add Back-end to path
sys.path.append(os.path.join(os.getcwd(), 'Back-end'))

from spotify_api import _make_spotify_request

class TestRateLimit(unittest.TestCase):
    @patch('spotify_api.requests.get')
    @patch('spotify_api.time.sleep')
    def test_rate_limit_retry(self, mock_sleep, mock_get):
        # Setup mock to return 429 twice, then 200
        response_429 = MagicMock()
        response_429.status_code = 429
        response_429.headers = {'Retry-After': '1'}
        
        response_200 = MagicMock()
        response_200.status_code = 200
        response_200.json.return_value = {'success': True}
        
        mock_get.side_effect = [response_429, response_429, response_200]
        
        # Call the function
        print("Testing rate limit retry...")
        response = _make_spotify_request('http://example.com', {}, max_retries=3)
        
        # Verify
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        print("✅ Rate limit retry worked as expected!")

if __name__ == '__main__':
    unittest.main()
