#!/usr/bin/env python3
"""
Test script for Hamming SEC-DED implementation
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main_app import hamming_encode, hamming_decode, get_sec_ded_hamming_params

def test_hamming_code():
    print("Testing Hamming SEC-DED implementation...")
    
    # Test 1: Basic encoding and decoding without errors
    print("\n1. Testing basic encode/decode:")
    test_data = [1, 0, 1, 1, 0, 0, 1, 0]  # 8-bit test data
    encoded = hamming_encode(test_data)
    print(f"Original data: {test_data}")
    print(f"Encoded: {encoded}")
    
    decoded_data, corrected, double_error = hamming_decode(encoded)
    print(f"Decoded data: {decoded_data}")
    print(f"Corrected: {corrected}, Double error: {double_error}")
    
    assert decoded_data == test_data, f"Decoded data {decoded_data} != original {test_data}"
    assert not corrected, "Should not indicate correction for valid data"
    assert not double_error, "Should not indicate double error for valid data"
    print("PASS: Basic encode/decode test passed")
    
    # Test 2: Single bit error correction
    print("\n2. Testing single bit error correction:")
    test_data2 = [1, 1, 0, 0, 1, 1, 0, 0]
    encoded2 = hamming_encode(test_data2)
    print(f"Original data: {test_data2}")
    print(f"Encoded: {encoded2}")
    
    # Introduce a single bit error
    corrupted_encoded = encoded2[:]
    corrupted_encoded[5] ^= 1  # Flip bit at position 5
    print(f"Corrupted encoded: {corrupted_encoded}")
    
    decoded_data2, corrected2, double_error2 = hamming_decode(corrupted_encoded)
    print(f"Decoded data: {decoded_data2}")
    print(f"Corrected: {corrected2}, Double error: {double_error2}")
    
    assert decoded_data2 == test_data2, f"Corrected data {decoded_data2} != original {test_data2}"
    assert corrected2, "Should indicate correction for single error"
    assert not double_error2, "Should not indicate double error for single error"
    print("PASS: Single bit error correction test passed")
    
    # Test 3: Double bit error detection
    print("\n3. Testing double bit error detection:")
    test_data3 = [1, 0, 1, 0, 1, 0, 1, 0]
    encoded3 = hamming_encode(test_data3)
    print(f"Original data: {test_data3}")
    print(f"Encoded: {encoded3}")
    
    # Introduce two bit errors
    corrupted_encoded2 = encoded3[:]
    corrupted_encoded2[2] ^= 1  # Flip bit at position 2
    corrupted_encoded2[7] ^= 1  # Flip bit at position 7
    print(f"Double corrupted encoded: {corrupted_encoded2}")
    
    decoded_data3, corrected3, double_error3 = hamming_decode(corrupted_encoded2)
    print(f"Decoded data: {decoded_data3}")
    print(f"Corrected: {corrected3}, Double error: {double_error3}")
    
    assert double_error3, "Should detect double error"
    print("PASS: Double bit error detection test passed")
    
    # Test 4: Parameter calculation
    print("\n4. Testing parameter calculation:")
    data_bits = 80  # 10 bytes = 80 bits
    r, total_len = get_sec_ded_hamming_params(data_bits)
    print(f"Data bits: {data_bits}, Parity bits needed: {r}, Total code length: {total_len}")
    print(f"Expected total length: {data_bits} + {r} = {data_bits + r}")
    assert total_len == data_bits + r, f"Total length mismatch: {total_len} != {data_bits + r}"
    print("PASS: Parameter calculation test passed")
    
    print("\nAll tests passed! Hamming SEC-DED implementation is working correctly.")

if __name__ == "__main__":
    test_hamming_code()