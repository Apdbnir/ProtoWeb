import unittest
import sys
import os
sys.path.append(os.path.dirname(__file__))

from main_app import CSMACDTransmitter

class TestCSMACDTransmitter(unittest.TestCase):
    def setUp(self):
        # Create a mock serial port object for testing
        class MockPort:
            def __init__(self):
                self.data = []
                self.is_open = True
            
            def write(self, data):
                self.data.extend(data)
        
        self.mock_port = MockPort()
        self.transmitter = CSMACDTransmitter(self.mock_port)

    def test_listen_channel(self):
        """Test channel listening with 70% busy probability"""
        busy_count = 0
        total_tests = 1000
        
        for _ in range(total_tests):
            if self.transmitter.listen_channel():
                busy_count += 1
        
        # The busy rate should be approximately 70%
        busy_rate = busy_count / total_tests
        self.assertAlmostEqual(busy_rate, 0.7, delta=0.1)  # Allow 10% tolerance

    def test_detect_collision(self):
        """Test collision detection with 30% probability"""
        collision_count = 0
        total_tests = 1000
        
        for _ in range(total_tests):
            if self.transmitter.detect_collision():
                collision_count += 1
        
        # The collision rate should be approximately 30%
        collision_rate = collision_count / total_tests
        self.assertAlmostEqual(collision_rate, 0.3, delta=0.1)  # Allow 10% tolerance

    def test_generate_backoff_time(self):
        """Test backoff time generation"""
        # Test with different collision counts
        for collision_count in [0, 1, 2, 5, 10]:
            backoff_time = self.transmitter.generate_backoff_time(collision_count)
            # Backoff time should be non-negative
            self.assertGreaterEqual(backoff_time, 0)
        
        # Test minimum CW (should be 7 at collision_count=0 since cw_min is 7)
        min_backoff = self.transmitter.generate_backoff_time(0)
        # Minimum possible value is 0 * 5 = 0 ms
        # Maximum possible value is 7 * 5 = 35 ms for first collision
        max_expected = 7 * 5  # cw_min * slot_time
        self.assertLessEqual(min_backoff, max_expected)
        
        # Test maximum backoff exponent
        max_backoff = self.transmitter.generate_backoff_time(20)  # More than max_backoff_exp
        # Should use max_backoff_exp and cw_max: (2^10 - 1) * 5 = 1023 * 5 = 5115 ms
        max_expected = self.transmitter.cw_max * 5  # cw_max * slot_time
        self.assertLessEqual(max_backoff, max_expected)

    def test_send_jam_signal(self):
        """Test jam signal sending"""
        initial_data_len = len(self.mock_port.data)
        self.transmitter.send_jam_signal()
        # Should have added 4 jam bytes (0xFF)
        self.assertEqual(len(self.mock_port.data), initial_data_len + 4)
        # Check that all added bytes are 0xFF (jam signal)
        for i in range(4):
            self.assertEqual(self.mock_port.data[initial_data_len + i], 0xFF)

if __name__ == '__main__':
    unittest.main()