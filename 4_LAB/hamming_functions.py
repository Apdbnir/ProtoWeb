import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '3_LAB'))

def get_sec_ded_hamming_params(data_bits_count):
    """
    Calculate parameters for SEC-DED Hamming code
    Returns (total_parity_bits, total_code_length) where total_parity_bits is number of parity bits and 
    total_code_length is the length of the encoded code
    """
    # For standard Hamming, we need r such that 2^r >= d + r + 1 where d is data bit count
    standard_parity_bits = 0
    while (2**standard_parity_bits) < (data_bits_count + standard_parity_bits + 1):
        standard_parity_bits += 1
    
    # For SEC-DED, we add one more parity bit (overall parity)
    overall_parity_bit = 1
    total_parity_bits = standard_parity_bits + overall_parity_bit
    total_code_length = data_bits_count + total_parity_bits
    
    return total_parity_bits, total_code_length

def calculate_hamming_parity_bits(data_bits):
    """
    Calculate Hamming parity bits for data_bits using the SEC-DED algorithm.
    This function returns the data bits with parity bits inserted at appropriate positions.
    For SEC-DED: we calculate standard Hamming parity bits, then add one overall parity bit.
    """
    # Convert data bits to a list for easier manipulation
    data = list(data_bits)
    
    # Calculate number of parity bits needed for SEC-DED
    m = len(data)  # Number of data bits
    standard_parity_bits = 0
    while (2**standard_parity_bits) < (m + standard_parity_bits + 1):
        standard_parity_bits += 1
    
    # For SEC-DED, add one more overall parity bit
    overall_parity_bit = 1
    total_parity_bits = standard_parity_bits + overall_parity_bit
    
    # Total code length
    n = m + total_parity_bits
    
    # Create the full code word with parity bits at positions that are powers of 2 (1-indexed)
    # Position 0 (index 0) will be the overall parity bit
    hamming_code = [0] * n
    
    # In SEC-DED Hamming, we typically reserve positions 1, 2, 4, 8, ... (powers of 2) for parity bits
    # and place data bits in other positions
    # The overall parity bit can go at the end or at position 0
    
    # Let's use 1-indexed positions for standard Hamming and put overall parity at the end
    # Positions 1, 2, 4, 8, etc. (1-indexed) will be parity bits
    # Other positions will be data bits
    
    # First, place data bits
    data_idx = 0
    for pos_1idx in range(1, n + 1):  # 1-indexed positions
        if (pos_1idx & (pos_1idx - 1)) != 0:  # Not a power of 2, so it's a data position
            if data_idx < len(data):
                hamming_code[pos_1idx - 1] = data[data_idx]
                data_idx += 1
    
    # Calculate regular Hamming parity bits (at power-of-2 positions 1-indexed)
    for i in range(standard_parity_bits):  # For each standard Hamming parity bit
        parity_pos_1idx = 1 << i  # Position of the parity bit in 1-indexed (1, 2, 4, 8, ...)
        if parity_pos_1idx <= n:  # If position is valid
            parity = 0
            
            # XOR all bits that this parity bit checks
            # A parity bit at position p (1-indexed) checks all bits where the p-th bit is set in the position
            for bit_pos_1idx in range(1, n + 1):  # 1-indexed
                if (bit_pos_1idx >> i) & 1:  # Check if the i-th bit is set in this position
                    if bit_pos_1idx != parity_pos_1idx:  # Don't include the parity bit itself
                        parity ^= hamming_code[bit_pos_1idx - 1]
            
            hamming_code[parity_pos_1idx - 1] = parity
    
    # Calculate the overall parity bit that covers all bits (including the regular parity bits)
    overall_parity = 0
    for i in range(n - 1):  # All bits except the overall parity bit position itself
        overall_parity ^= hamming_code[i]
    # Put the overall parity in the last position
    hamming_code[n - 1] = overall_parity
    
    return hamming_code

def hamming_encode(data_bits):
    """
    Full Hamming SEC-DED encoding process: calculate parity bits
    """
    return calculate_hamming_parity_bits(data_bits)

def hamming_decode(encoded_bits):
    """
    Decode Hamming SEC-DED code and correct single-bit errors, detect double-bit errors
    Returns (corrected_data_bits, is_corrected, is_double_error)
    """
    n = len(encoded_bits)
    
    # Calculate the syndrome (position of error if single error exists)
    # The syndrome calculation excludes the overall parity bit
    syndrome = 0
    
    for i in range(n):
        if encoded_bits[i]:
            syndrome ^= (i + 1)  # Using 1-indexed positions
    
    # Calculate the overall parity (all bits) - this is the parity of the entire code
    total_parity = 0
    for bit in encoded_bits:
        total_parity ^= bit
    
    if syndrome == 0 and total_parity == 0:
        # No error
        error_corrected = False
        double_error = False
    elif syndrome != 0 and total_parity == 1:
        # Single error - can be corrected
        # Syndrome indicates the 1-indexed position of the error
        if syndrome <= n:
            corrected_bits = encoded_bits[:]
            corrected_bits[syndrome - 1] ^= 1  # Flip the error bit
        else:
            corrected_bits = encoded_bits[:]  # Can't correct, keep original
        error_corrected = True
        double_error = False
        encoded_bits = corrected_bits
    elif syndrome != 0 and total_parity == 0:
        # Double error - detected but cannot be corrected
        error_corrected = False
        double_error = True
    else:
        # This case shouldn't occur with proper SEC-DED code (syndrome=0, total_parity=1)
        # This would mean even number of errors caused syndrome to be 0 but overall parity to be 1
        error_corrected = False
        double_error = True
    
    # Extract data bits (skip parity positions: 1, 2, 4, 8, ... - 1-indexed)
    # In Hamming SEC-DED, regular parity bits are at positions that are powers of 2 (1-indexed)
    # The last bit should be the overall parity, so exclude it too
    data_bits = []
    for i in range(n):
        pos = i + 1  # 1-indexed position
        # A position is NOT a data bit if:
        # 1. It's a power of 2 (regular Hamming parity) OR
        # 2. It's the last bit (overall parity for SEC-DED)
        if (pos & (pos - 1)) != 0:  # Not power of 2 AND not the last position
            data_bits.append(encoded_bits[i])
    
    return data_bits, error_corrected, double_error

# Test the implementation
if __name__ == "__main__":
    # Test basic functionality
    test_data = [1, 0, 1, 1]  # 4 data bits
    print(f"Original data: {test_data}")
    
    encoded = hamming_encode(test_data)
    print(f"Encoded with Hamming SEC-DED: {encoded}")
    
    # Test with a single-bit error
    corrupted = encoded[:]
    corrupted[2] = 1 - corrupted[2]  # Flip one bit
    print(f"Corrupted data: {corrupted}")
    
    decoded, corrected, double_error = hamming_decode(corrupted)
    print(f"Decoded: {decoded}")
    print(f"Error corrected: {corrected}")
    print(f"Double error detected: {double_error}")
    
    print("\nHamming SEC-DED functions are available for import.")