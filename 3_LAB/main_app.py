import sys
import os
import serial
import serial.tools.list_ports
import threading
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import pyqtSignal, QObject, QThread
from PyQt6.QtGui import QTextCharFormat, QColor, QFont
import random

# Импортируем наш сгенерированный класс дизайна
from ui_main_window import Ui_MainWindow

# --- Single instance lock ---
# Global variable to hold the file handle to prevent it from being garbage collected
lock_file_handle = None

def is_already_running():
    """
    Checks if another instance of the application is running using a lock file.
    On Windows, it uses msvcrt. On POSIX, it uses fcntl.
    Returns True if another instance is found, False otherwise.
    """
    global lock_file_handle
    # Place lock file in user's home directory for robustness
    lock_file_path = os.path.join(os.path.expanduser("~"), "com_communicator.lock")

    try:
        if sys.platform == "win32":
            import msvcrt
            # Open the file, creating it if it doesn't exist
            lock_file_handle = open(lock_file_path, 'w')
            try:
                # Try to get an exclusive, non-blocking lock
                msvcrt.locking(lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                # If we got the lock, we are the first instance
                return False
            except IOError:
                # If we failed to get the lock, another instance is running
                lock_file_handle.close() # Close the handle
                return True
        else: # For Linux/macOS
            import fcntl
            lock_file_handle = open(lock_file_path, 'w')
            try:
                # Try to get an exclusive, non-blocking lock
                fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # If we got the lock, we are the first instance
                return False
            except IOError:
                # If we failed to get the lock, another instance is running
                lock_file_handle.close()
                return True
    except Exception as e:
        # If any other error occurs, it's safer to allow the app to run
        print(f"Could not create lock file: {e}")
        return False

# --- Hamming SEC-DED Code Implementation ---

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
        if (pos & (pos - 1)) != 0 and pos != n:  # Not power of 2 AND not the last position
            data_bits.append(encoded_bits[i])
    
    return data_bits, error_corrected, double_error

# --- Класс-работник для чтения порта в отдельном потоке ---
class SerialWorker(QObject):
    data_received = pyqtSignal(bytes)

    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self._is_running = True

    def run(self):
        """Запускается в отдельном потоке для чтения данных из порта."""
        while self._is_running:
            try:
                if self.serial_port and self.serial_port.is_open:
                    # Читаем посимвольно (по одному байту)
                    byte = self.serial_port.read(1)
                    if byte:
                        self.data_received.emit(byte)
            except (serial.SerialException, OSError):
                break # Выходим из цикла при ошибке порта
        print("Поток чтения завершен.")

    def stop(self):
        """Сигнал для остановки потока."""
        self._is_running = False

# --- Основной класс приложения ---
class CommunicatorApp(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.setWindowTitle("COM Communicator - Улучшенная версия (3_LAB - Hamming FCS)")

        # Устанавливаем цвет фона для окон вывода, чтобы сделать их более заметными
        # Используем стандартный цвет фона Qt
        self.output_text.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.output_text_tab2.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.debug_text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 9px;")

        # --- Константы для кадрирования и стаффинга ---
        self.N = 9
        self.DATA_LENGTH = self.N + 1  # n + 1 = 10 bytes for data field
        self.FLAG_START = b'@'
        self.FLAG_END = bytes([ord('a') + self.N - 1])  # 'a' + 9 - 1 = 'i'
        self.FLAG = self.FLAG_START + self.FLAG_END
        self.DEST_ADDR = b'\x00'  # Always 0 as per requirements
        self.ESC = b'\x1B'
        # Словарь для стаффинга: заменяем флаги и ESC-символы
        self.STUFF_MAP = {
            self.FLAG_START: self.ESC + self.FLAG_START,  # Replace '@' with ESC + '@'
            self.FLAG_END: self.ESC + self.FLAG_END,      # Replace flag end character with ESC + flag end
            self.ESC: self.ESC + self.ESC                 # Replace ESC with ESC + ESC
        }
        # Обратный словарь для де-стаффинга - use bytes, not bytearray
        self.UNSTUFF_MAP = {}
        for k, v in self.STUFF_MAP.items():
            self.UNSTUFF_MAP[v] = k
        
        # Calculate FCS length based on Hamming SEC-DED requirements
        # For DATA_LENGTH = 10 bytes = 80 bits of data, we need to compute the total Hamming code length
        # For SEC-DED (Single Error Correction, Double Error Detection), we need:
        # 2^r >= m + r + 1 for error correction + 1 additional bit for double error detection
        # where m is the number of data bits (80 in our case)
        # So we need: 2^r >= 80 + r + 1 => 2^r >= 81 + r
        data_bits_count = self.DATA_LENGTH * 8  # 10 bytes = 80 bits
        r = 0
        while (2**r) < (data_bits_count + r + 1):
            r += 1
        # For SEC-DED, we need one additional parity bit, so total parity bits = r + 1
        total_parity_bits = r + 1
        self.fcs_bits_count = total_parity_bits
        self.FCS_LENGTH = (self.fcs_bits_count + 7) // 8  # Convert bits to bytes, rounding up

        # --- Переменные состояния для экземпляра 1 ---
        self.port_tx_name_1 = None
        self.port_rx_name_1 = None
        self.port_tx_1 = None
        self.port_rx_1 = None
        self.worker_1 = None
        self.receive_thread_1 = None
        self.sent_bytes_count_1 = 0
        self.rx_buffer_1 = bytearray()

        # --- Переменные состояния для экземпляра 2 ---
        self.port_tx_name_2 = None
        self.port_rx_name_2 = None
        self.port_tx_2 = None
        self.port_rx_2 = None
        self.worker_2 = None
        self.receive_thread_2 = None
        self.sent_bytes_count_2 = 0
        self.rx_buffer_2 = bytearray()
        
        self.fixed_baud_rate = 9600 # Скорость фиксирована, как в задании

        # --- Настройка UI ---
        self.parity_combo.addItems(['None', 'Even', 'Odd', 'Mark', 'Space'])
        self.parity_combo_tab2.addItems(['None', 'Even', 'Odd', 'Mark', 'Space'])

        # --- Подключение сигналов к слотам (обработчикам) ---
        self.connect_button.clicked.connect(self.connect_ports_1)
        self.disconnect_button.clicked.connect(self.disconnect_ports_1)
        self.send_button.clicked.connect(self.send_data_1)
        
        self.connect_button_tab2.clicked.connect(self.connect_ports_2)
        self.disconnect_button_tab2.clicked.connect(self.disconnect_ports_2)
        self.send_button_2.clicked.connect(self.send_data_2)
        
        # --- Первоначальная настройка ---
        self.log_debug("Приложение запущено.")
        self.populate_ports()
        self.toggle_controls_state_1(is_connected=False)
        self.toggle_controls_state_2(is_connected=False)
        self.update_status_labels_1()
        self.update_status_labels_2()

    def log_debug(self, message):
        """Выводит сообщение в отладочное окно с меткой времени."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        # Add debug messages with gray color to distinguish from regular messages
        self.debug_text.appendHtml(f"<span style='color: #888888;'>[{timestamp}] {message}</span>")

    def calculate_fcs(self, data_bytes):
        """
        Calculate FCS field using Hamming SEC-DED code for the given data bytes
        The FCS contains the entire Hamming SEC-DED encoded word.
        """
        # Convert data bytes to bits
        data_bits = []
        for byte in data_bytes:
            for i in range(7, -1, -1):  # MSB first
                data_bits.append((byte >> i) & 1)
        
        # Apply Hamming SEC-DED encoding to get the complete code word
        encoded_bits = hamming_encode(data_bits)
        
        # Convert the encoded bits to bytes
        fcs_bytes = []
        for i in range(0, len(encoded_bits), 8):
            byte_val = 0
            for j in range(min(8, len(encoded_bits) - i)):
                if i + j < len(encoded_bits):
                    byte_val |= (encoded_bits[i + j] << (7 - j))
            fcs_bytes.append(byte_val)
        
        # Pad with zeros to reach FCS_LENGTH if needed
        while len(fcs_bytes) < self.FCS_LENGTH:
            fcs_bytes.append(0)
        
        return bytes(fcs_bytes[:self.FCS_LENGTH])

    def verify_fcs(self, received_data, received_fcs):
        """
        Verify the FCS field and correct single-bit errors if any.
        This function reconstructs the complete Hamming codeword from the received data and FCS,
        then decodes it to detect/correct errors.
        """
        # Convert received data bytes to bits
        data_bits = []
        for byte in received_data:
            for i in range(7, -1, -1):  # MSB first
                data_bits.append((byte >> i) & 1)
        
        # Convert received FCS bytes to bits
        fcs_bits = []
        for byte in received_fcs:
            for i in range(7, -1, -1):  # MSB first
                fcs_bits.append((byte >> i) & 1)
        
        # Reconstruct the complete encoded word by combining data bits and FCS bits
        # Since the FCS contains the parity bits and the data we have is original data (possibly corrupted),
        # we need to form the complete codeword.
        # Actually, the received data might be corrupted, so we need to check if it's valid against the FCS
        
        # For verification, we should regenerate the Hamming code from the received data
        # and compare with received FCS to detect errors
        regenerated_hamming_code = hamming_encode(data_bits)
        
        # We'll create the full codeword by putting data bits in data positions and FCS bits in parity positions
        # This is complex, so instead let's just decode the received FCS to understand the intended codeword
        # Actually, we should form the full received codeword and then apply Hamming decoding
        
        # Let's form the received codeword by placing the received data in data positions
        # and received FCS bits in parity positions, then decode
        r, total_length = get_sec_ded_hamming_params(len(data_bits))
        
        # Create the received codeword: fill with data bits in data positions and FCS bits in parity positions
        received_codeword = [0] * total_length
        data_idx = 0
        
        # Fill data positions (non-powers of 2, 1-indexed)
        for pos in range(1, total_length + 1):
            if (pos & (pos - 1)) != 0:  # Not a power of 2, so it's a data position
                if data_idx < len(data_bits):
                    received_codeword[pos - 1] = data_bits[data_idx]
                    data_idx += 1
        
        # Fill parity positions with received FCS bits
        fcs_idx = 0
        for pos in range(1, total_length + 1):
            if (pos & (pos - 1)) == 0:  # Power of 2, so it's a parity position
                if fcs_idx < len(fcs_bits):
                    received_codeword[pos - 1] = fcs_bits[fcs_idx]
                    fcs_idx += 1
        
        # Decode the received codeword
        corrected_data_bits, corrected, double_error = hamming_decode(received_codeword)
        
        # Convert corrected data bits back to bytes
        corrected_bytes = []
        for i in range(0, len(corrected_data_bits), 8):
            byte_val = 0
            for j in range(min(8, len(corrected_data_bits) - i)):
                if i + j < len(corrected_data_bits):
                    byte_val |= (corrected_data_bits[i + j] << (7 - j))
            corrected_bytes.append(byte_val)
        
        return bytes(corrected_bytes), corrected, double_error

    def apply_bit_corruption(self, data_bytes):
        """
        Apply random bit corruption to data bytes with specified probabilities:
        - 40% chance to corrupt single bit
        - 25% chance to corrupt two bits
        """
        # Convert to mutable bytearray
        data = bytearray(data_bytes)
        
        # Determine how many bits to corrupt based on probabilities
        rand_val = random.random()
        
        if rand_val < 0.40:  # 40% chance for single bit corruption
            # Corrupt one bit
            byte_idx = random.randint(0, len(data) - 1)
            bit_idx = random.randint(0, 7)
            data[byte_idx] ^= (1 << bit_idx)
            self.log_debug(f"Применена одиночная битовая ошибка: байт {byte_idx}, бит {bit_idx}")
        elif rand_val < 0.65:  # Additional 25% chance (0.40 + 0.25 = 0.65) for double bit corruption
            # Corrupt two bits
            # First bit
            byte_idx1 = random.randint(0, len(data) - 1)
            bit_idx1 = random.randint(0, 7)
            data[byte_idx1] ^= (1 << bit_idx1)
            # Second bit (ensure it's different from first)
            while True:
                byte_idx2 = random.randint(0, len(data) - 1)
                bit_idx2 = random.randint(0, 7)
                if byte_idx1 != byte_idx2 or bit_idx1 != bit_idx2:
                    data[byte_idx2] ^= (1 << bit_idx2)
                    break
            self.log_debug(f"Применена двойная битовая ошибка: байты ({byte_idx1},{byte_idx2}), биты ({bit_idx1},{bit_idx2})")
        
        return bytes(data)

    def prepare_data(self, text_data, source_port_num):
        """
        Подготавливает данные для отправки: разбивает на кадры,
        дополняет нулями, вычисляет FCS, применяет искажение, затем выполняет байт-стаффинг.
        """
        try:
            source_addr = bytes([source_port_num])
        except (TypeError, ValueError):
            self.log_debug(f"Ошибка: неверный номер порта {source_port_num}. Используется 0.")
            source_addr = b'\x00'

        data_bytes = text_data.encode('utf-8')
        
        # 1. Разбиение на чанки (пакеты) - каждый чанк будет содержать DATA_LENGTH байт
        chunks = [data_bytes[i:i + self.DATA_LENGTH] for i in range(0, len(data_bytes), self.DATA_LENGTH)]
        
        prepared_frames = []
        display_html = ""

        for i, chunk in enumerate(chunks):
            # 2. Дополнение нулями до DATA_LENGTH байт
            if len(chunk) < self.DATA_LENGTH:
                chunk = chunk.ljust(self.DATA_LENGTH, b'\x00')

            # 3. Calculate FCS for the original (non-corrupted) data
            fcs = self.calculate_fcs(chunk)
            
            # 4. Apply random bit corruption to data field (before stuffing)
            corrupted_chunk = self.apply_bit_corruption(chunk)
            
            # 5. Байт-стаффинг (apply to corrupted data + fcs fields)
            data_with_fcs = corrupted_chunk + fcs
            stuffed_data_with_fcs = bytearray()
            stuffed_indices = set()
            for byte_index, byte in enumerate(data_with_fcs):
                byte_val = bytes([byte])
                if byte_val in self.STUFF_MAP:
                    stuffed_data_with_fcs.extend(self.STUFF_MAP[byte_val])
                    # Запоминаем индекс, где произошел стаффинг
                    stuffed_indices.add(len(stuffed_data_with_fcs) - 2)
                    stuffed_indices.add(len(stuffed_data_with_fcs) - 1)
                else:
                    stuffed_data_with_fcs.extend(byte_val)
            
            # 6. Сборка кадра в правильном порядке:
            # Flag (2 байта) + Source Address (1 байт) + Destination Address (1 байт) + Data (N+1 байт) + FCS (var bytes)
            frame = self.FLAG + source_addr + self.DEST_ADDR + stuffed_data_with_fcs
            
            prepared_frames.append(frame)

            # 7. Формирование строки для отображения с правильным порядком и подсветкой FCS
            display_html += f"<div style='margin: 2px 0;'><b>Кадр {i+1}:</b> "
            display_html += f"<span style='color: #009900; font-weight: bold;'>{self.FLAG.hex().upper()}</span> "  # Flag: 2 байта (green)
            display_html += f"<span style='color: #CCCC00;'>{source_addr.hex().upper()}</span> "  # Source Address: 1 байт (yellow)
            display_html += f"<span style='color: grey;'>{self.DEST_ADDR.hex().upper()}</span> "  # Destination Address: 1 байт
            
            # Отображение данных с подсветкой FCS и стаффинга
            # To correctly identify which bytes were originally data vs FCS after stuffing,
            # we need to simulate the unstuffing process and track positions
            stuffed_hex = ""
            
            # Create a mapping to track original positions
            original_data_part = corrupted_chunk  # First part is data
            original_fcs_part = fcs  # Second part is FCS
            original_data_fcs = original_data_part + original_fcs_part  # Combined
            
            # Simulate what the unstuffing would produce to map positions
            # We'll iterate through stuffed_data_with_fcs and figure out which original byte each corresponds to
            unstuffed_byte_idx = 0
            i = 0
            while i < len(stuffed_data_with_fcs):
                current_byte = stuffed_data_with_fcs[i]
                
                # Check if this is part of a stuffing sequence
                is_part_of_stuffing = False
                if i < len(stuffed_data_with_fcs) - 1:
                    potential_seq = bytes([stuffed_data_with_fcs[i], stuffed_data_with_fcs[i+1]])
                    if potential_seq in self.UNSTUFF_MAP:
                        is_part_of_stuffing = True
                        # First byte of sequence is original, second is the stuffing
                        if i == len(stuffed_data_with_fcs) - 1:  # This shouldn't happen if properly formatted
                            is_part_of_stuffing = False
                        
                if is_part_of_stuffing:
                    # This is the first byte of a stuffing sequence (original byte)
                    # Check if it belongs to data or FCS
                    is_fcs_byte = (unstuffed_byte_idx >= len(original_data_part))
                    
                    if is_fcs_byte:
                        stuffed_hex += f"<span style='color: orange; font-weight: bold; text-decoration: underline;'>{current_byte:02X}</span> "  # FCS byte
                    else:
                        stuffed_hex += f"<span style='color: red; font-weight: bold;'>{current_byte:02X}</span> "  # Data byte after stuffing
                    unstuffed_byte_idx += 1
                    i += 2  # Skip both bytes of the stuffing sequence
                else:
                    # This is not part of a stuffing sequence, it's an original byte
                    is_fcs_byte = (unstuffed_byte_idx >= len(original_data_part))
                    
                    if is_fcs_byte:
                        stuffed_hex += f"<span style='color: orange; font-weight: bold; text-decoration: underline;'>{current_byte:02X}</span> "  # FCS byte
                    else:
                        stuffed_hex += f"{current_byte:02X} "  # Regular data byte
                    unstuffed_byte_idx += 1
                    i += 1

            display_html += stuffed_hex
            display_html += "</div>"

        return prepared_frames, display_html

    def count_stuffed_bytes_before(self, stuffed_indices, pos):
        """Count how many stuffing bytes occurred before position pos"""
        count = 0
        for idx in stuffed_indices:
            if idx < pos:
                count += 1
        return count

    def populate_ports(self):
        """
        Populates the COM port selection combo boxes with available ports.
        """
        self.log_debug("Поиск COM-портов...")
        
        detailed_ports = serial.tools.list_ports.comports()
        
        self.log_debug("--- ОБНАРУЖЕННЫЕ COM-ПОРТЫ ---")
        if not detailed_ports:
            self.log_debug("Нет доступных COM-портов.")
        else:
            for port in detailed_ports:
                self.log_debug(f"  - Устройство: {port.device}")
                self.log_debug(f"    Описание: {port.description}")
                self.log_debug(f"    HWID: {port.hwid}")
        self.log_debug("---------------------------------")

        ports = sorted([port.device for port in detailed_ports])
        
        self.port_combo.addItems(ports)
        self.port_combo_2.addItems(ports)
        self.port_combo_tab2.addItems(ports)
        self.port_combo_2_tab2.addItems(ports)

        if len(ports) < 2:
            self.log_debug("ВНИМАНИЕ: Найдено менее 2 COM-портов.")
            QMessageBox.warning(self, "Внимание", "Для работы требуется минимум 2 COM-порта.")

    def connect_ports_1(self):
        """Подключается к COM-портам, выбранным в выпадающих списках."""
        tx_port_name = self.port_combo.currentText()
        rx_port_name = self.port_combo_2.currentText()

        if not tx_port_name or not rx_port_name:
            QMessageBox.warning(self, "Ошибка", "Порты не выбраны. Выберите порты для передачи и приема.")
            return

        if tx_port_name == rx_port_name:
            QMessageBox.warning(self, "Ошибка", "Порт для передачи и приема не может быть одинаковым.")
            return

        self.log_debug(f"Попытка подключения: Tx={tx_port_name}, Rx={rx_port_name}")

        parity_map = {'None': serial.PARITY_NONE, 'Even': serial.PARITY_EVEN, 'Odd': serial.PARITY_ODD, 'Mark': serial.PARITY_MARK, 'Space': serial.PARITY_SPACE}
        selected_parity = parity_map.get(self.parity_combo.currentText())

        try:
            self.port_tx_1 = serial.Serial(tx_port_name, baudrate=self.fixed_baud_rate, parity=selected_parity, timeout=1)
            self.port_rx_1 = serial.Serial(rx_port_name, baudrate=self.fixed_baud_rate, parity=selected_parity, timeout=1)
            self.log_debug(f"Порт {tx_port_name} открыт для передачи.")
            self.log_debug(f"Порт {rx_port_name} открыт для приема.")
        except serial.SerialException as e:
            QMessageBox.critical(self, "Ошибка подключения", f"Не удалось открыть порты:\n{e}")
            self.log_debug(f"ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
            return

        self.toggle_controls_state_1(is_connected=True)
        self.update_status_labels_1()

        # Запускаем поток для чтения данных
        self.worker_1 = SerialWorker(self.port_rx_1)
        self.receive_thread_1 = QThread()
        self.worker_1.moveToThread(self.receive_thread_1)
        self.receive_thread_1.started.connect(self.worker_1.run)
        self.worker_1.data_received.connect(self.on_data_received_1)
        self.receive_thread_1.start()
        self.log_debug("Поток на прием данных запущен.")

    def connect_ports_2(self):
        """Подключается к COM-портам, выбранным в выпадающих списках на второй вкладке."""
        tx_port_name = self.port_combo_tab2.currentText()
        rx_port_name = self.port_combo_2_tab2.currentText()

        if not tx_port_name or not rx_port_name:
            QMessageBox.warning(self, "Ошибка", "Порты не выбраны. Выберите порты для передачи и приема.")
            return

        if tx_port_name == rx_port_name:
            QMessageBox.warning(self, "Ошибка", "Порт для передачи и приема не может быть одинаковым.")
            return

        self.log_debug(f"Попытка подключения (экземпляр 2): Tx={tx_port_name}, Rx={rx_port_name}")

        parity_map = {'None': serial.PARITY_NONE, 'Even': serial.PARITY_EVEN, 'Odd': serial.PARITY_ODD, 'Mark': serial.PARITY_MARK, 'Space': serial.PARITY_SPACE}
        selected_parity = parity_map.get(self.parity_combo_tab2.currentText())

        try:
            self.port_tx_2 = serial.Serial(tx_port_name, baudrate=self.fixed_baud_rate, parity=selected_parity, timeout=1)
            self.port_rx_2 = serial.Serial(rx_port_name, baudrate=self.fixed_baud_rate, parity=selected_parity, timeout=1)
            self.log_debug(f"Порт {tx_port_name} открыт для передачи (экземпляр 2).")
            self.log_debug(f"Порт {rx_port_name} открыт для приема (экземпляр 2).")
        except serial.SerialException as e:
            QMessageBox.critical(self, "Ошибка подключения", f"Не удалось открыть порты:\n{e}")
            self.log_debug(f"ОШИБКА ПОДКЛЮЧЕНИЯ (экземпляр 2): {e}")
            return

        self.toggle_controls_state_2(is_connected=True)
        self.update_status_labels_2()

        # Запускаем поток для чтения данных
        self.worker_2 = SerialWorker(self.port_rx_2)
        self.receive_thread_2 = QThread()
        self.worker_2.moveToThread(self.receive_thread_2)
        self.receive_thread_2.started.connect(self.worker_2.run)
        self.worker_2.data_received.connect(self.on_data_received_2)
        self.receive_thread_2.start()
        self.log_debug("Поток на прием данных запущен (экземпляр 2).")

    def disconnect_ports_1(self):
        """Отключается от COM-портов и останавливает поток."""
        if self.worker_1: self.worker_1.stop()
        if self.receive_thread_1:
            self.receive_thread_1.quit()
            self.receive_thread_1.wait()

        if self.port_tx_1 and self.port_tx_1.is_open:
            self.port_tx_1.close()
            self.log_debug(f"Порт {self.port_tx_1.name} закрыт.")
        if self.port_rx_1 and self.port_rx_1.is_open:
            self.port_rx_1.close()
            self.log_debug(f"Порт {self.port_rx_1.name} закрыт.")

        self.toggle_controls_state_1(is_connected=False)
        self.log_debug("Соединение разорвано.")

    def disconnect_ports_2(self):
        """Отключается от COM-портов и останавливает поток (экземпляр 2)."""
        if self.worker_2: self.worker_2.stop()
        if self.receive_thread_2:
            self.receive_thread_2.quit()
            self.receive_thread_2.wait()

        if self.port_tx_2 and self.port_tx_2.is_open:
            self.port_tx_2.close()
            self.log_debug(f"Порт {self.port_tx_2.name} закрыт (экземпляр 2).")
        if self.port_rx_2 and self.port_rx_2.is_open:
            self.port_rx_2.close()
            self.log_debug(f"Порт {self.port_rx_2.name} закрыт (экземпляр 2).")

        self.toggle_controls_state_2(is_connected=False)
        self.log_debug("Соединение разорвано (экземпляр 2).")

    def on_data_received_1(self, data_bytes):
        """Обрабатывает принятые байты, ищет кадры, выполняет де-стаффинг и отображает данные."""
        try:
            self.rx_buffer_1.extend(data_bytes)

            # Пытаемся найти и обработать все полные кадры в буфере
            while True:
                # Ищем начало кадра (флаг)
                start_index = self.rx_buffer_1.find(self.FLAG)
                if start_index == -1:
                    # Нет начала кадра, очищаем буфер если данных много
                    if len(self.rx_buffer_1) > 100:
                        self.rx_buffer_1 = self.rx_buffer_1[-50:]  # Сохраняем последние 50 байт на случай частичного кадра
                    return  # Нет полного кадра для обработки

                # Calculate minimum frame size: FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS
                min_frame_size = 4 + self.DATA_LENGTH + self.FCS_LENGTH  # 4 for header + data + minimum FCS
                
                if len(self.rx_buffer_1) - start_index < min_frame_size:
                    # Недостаточно данных для полного кадра, ждем больше
                    return

                # Извлекаем потенциальный кадр
                potential_frame = self.rx_buffer_1[start_index:]
                
                # Извлекаем фиксированные поля
                source_addr = potential_frame[2:3]
                dest_addr = potential_frame[3:4]
                
                # Extract the stuffed data+FCS field
                raw_data_with_fcs = potential_frame[4:]  # Everything after header
                
                # Perform unstuffing to extract actual data and FCS
                unstuffed_data_with_fcs = bytearray()
                i = 0
                while i < len(raw_data_with_fcs):
                    # Check if we have enough bytes for a potential stuffing sequence
                    if i + 1 < len(raw_data_with_fcs):
                        sequence = bytes(raw_data_with_fcs[i:i+2])
                        if sequence in self.UNSTUFF_MAP:
                            unstuffed_data_with_fcs.extend(self.UNSTUFF_MAP[sequence])
                            i += 2
                        else:
                            unstuffed_data_with_fcs.extend(bytes([raw_data_with_fcs[i]]))
                            i += 1
                    else:
                        # Only one byte left
                        unstuffed_data_with_fcs.extend(bytes([raw_data_with_fcs[i]]))
                        i += 1

                # Now extract actual data and FCS from unstuffed data
                if len(unstuffed_data_with_fcs) < self.DATA_LENGTH + self.FCS_LENGTH:
                    # Not enough data, need to continue waiting
                    return

                # Extract data and FCS
                received_data = bytes(unstuffed_data_with_fcs[:self.DATA_LENGTH])
                received_fcs = bytes(unstuffed_data_with_fcs[self.DATA_LENGTH:self.DATA_LENGTH + self.FCS_LENGTH])
                
                # Verify FCS and correct errors if possible
                corrected_data, corrected, double_error = self.verify_fcs(received_data, received_fcs)
                
                # Calculate actual frame size to remove from buffer
                # This is tricky - we need to calculate based on the stuffed data length
                actual_frame_size = 4 + len(raw_data_with_fcs)  # Header + stuffed data+FCS length
                
                # Remove processed frame from buffer
                next_frame_start = start_index + actual_frame_size
                if next_frame_start <= len(self.rx_buffer_1):
                    self.rx_buffer_1 = self.rx_buffer_1[next_frame_start:]
                else:
                    self.rx_buffer_1 = bytearray()  # Clear if something went wrong

                # Handle errors if detected
                if double_error:
                    self.log_debug("Обнаружена двойная ошибка в кадре, невозможно исправить!")
                elif corrected:
                    self.log_debug("Исправлена одиночная ошибка в кадре.")
                
                # Process the (potentially corrected) data
                try:
                    cleaned_payload = corrected_data.rstrip(b'\x00')
                    text = cleaned_payload.decode('utf-8', errors='replace')
                    # Add received packet data with different styling
                    if double_error:
                        self.output_text_tab2.appendHtml(f"<span style='color: red; font-style: italic;'>[ПАКЕТ С ОШИБКОЙ] {text}</span>")
                    elif corrected:
                        self.output_text_tab2.appendHtml(f"<span style='color: orange; font-style: italic;'>[ПАКЕТ С ИСПРАВЛЕННОЙ ОШИБКОЙ] {text}</span>")
                    else:
                        self.output_text_tab2.appendHtml(f"<span style='color: #CCCC00; font-style: italic;'>[ПАКЕТ] {text}</span>")
                    self.log_debug(f"Принят и обработан кадр от порта {source_addr[0]}, извлечено {len(corrected_data)} байт данных.")
                except UnicodeDecodeError:
                    self.log_debug("Ошибка декодирования принятых данных.")
                except Exception as e:
                    self.log_debug(f"Ошибка обработки данных: {e}")
        except Exception as e:
            self.log_debug(f"Критическая ошибка в on_data_received_1: {e}")


    def on_data_received_2(self, data_bytes):
        """Обрабатывает принятые байты, ищет кадры, выполняет де-стаффинг и отображает данные (экземпляр 2)."""
        try:
            self.rx_buffer_2.extend(data_bytes)

            # Пытаемся найти и обработать все полные кадры в буфере
            while True:
                # Ищем начало кадра (флаг)
                start_index = self.rx_buffer_2.find(self.FLAG)
                if start_index == -1:
                    # Нет начала кадра, очищаем буфер если данных много
                    if len(self.rx_buffer_2) > 100:
                        self.rx_buffer_2 = self.rx_buffer_2[-50:]  # Сохраняем последние 50 байт на случай частичного кадра
                    return  # Нет полного кадра для обработки

                # Calculate minimum frame size: FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS
                min_frame_size = 4 + self.DATA_LENGTH + self.FCS_LENGTH  # 4 for header + data + minimum FCS
                
                if len(self.rx_buffer_2) - start_index < min_frame_size:
                    # Недостаточно данных для полного кадра, ждем больше
                    return

                # Извлекаем потенциальный кадр
                potential_frame = self.rx_buffer_2[start_index:]
                
                # Извлекаем фиксированные поля
                source_addr = potential_frame[2:3]
                dest_addr = potential_frame[3:4]
                
                # Extract the stuffed data+FCS field
                raw_data_with_fcs = potential_frame[4:]  # Everything after header
                
                # Perform unstuffing to extract actual data and FCS
                unstuffed_data_with_fcs = bytearray()
                i = 0
                while i < len(raw_data_with_fcs):
                    # Check if we have enough bytes for a potential stuffing sequence
                    if i + 1 < len(raw_data_with_fcs):
                        sequence = bytes(raw_data_with_fcs[i:i+2])
                        if sequence in self.UNSTUFF_MAP:
                            unstuffed_data_with_fcs.extend(self.UNSTUFF_MAP[sequence])
                            i += 2
                        else:
                            unstuffed_data_with_fcs.extend(bytes([raw_data_with_fcs[i]]))
                            i += 1
                    else:
                        # Only one byte left
                        unstuffed_data_with_fcs.extend(bytes([raw_data_with_fcs[i]]))
                        i += 1

                # Now extract actual data and FCS from unstuffed data
                if len(unstuffed_data_with_fcs) < self.DATA_LENGTH + self.FCS_LENGTH:
                    # Not enough data, need to continue waiting
                    return

                # Extract data and FCS
                received_data = bytes(unstuffed_data_with_fcs[:self.DATA_LENGTH])
                received_fcs = bytes(unstuffed_data_with_fcs[self.DATA_LENGTH:self.DATA_LENGTH + self.FCS_LENGTH])
                
                # Verify FCS and correct errors if possible
                corrected_data, corrected, double_error = self.verify_fcs(received_data, received_fcs)
                
                # Calculate actual frame size to remove from buffer
                # This is tricky - we need to calculate based on the stuffed data length
                actual_frame_size = 4 + len(raw_data_with_fcs)  # Header + stuffed data+FCS length
                
                # Remove processed frame from buffer
                next_frame_start = start_index + actual_frame_size
                if next_frame_start <= len(self.rx_buffer_2):
                    self.rx_buffer_2 = self.rx_buffer_2[next_frame_start:]
                else:
                    self.rx_buffer_2 = bytearray()  # Clear if something went wrong

                # Handle errors if detected
                if double_error:
                    self.log_debug("Обнаружена двойная ошибка в кадре (экземпляр 2), невозможно исправить!")
                elif corrected:
                    self.log_debug("Исправлена одиночная ошибка в кадре (экземпляр 2).")
                
                # Process the (potentially corrected) data
                try:
                    cleaned_payload = corrected_data.rstrip(b'\x00')
                    text = cleaned_payload.decode('utf-8', errors='replace')
                    # Add received packet data with different styling
                    if double_error:
                        self.output_text.appendHtml(f"<span style='color: red; font-style: italic;'>[ПАКЕТ С ОШИБКОЙ] {text}</span>")
                    elif corrected:
                        self.output_text.appendHtml(f"<span style='color: orange; font-style: italic;'>[ПАКЕТ С ИСПРАВЛЕННОЙ ОШИБКОЙ] {text}</span>")
                    else:
                        self.output_text.appendHtml(f"<span style='color: #CCCC00; font-style: italic;'>[ПАКЕТ] {text}</span>")
                    self.log_debug(f"Принят и обработан кадр от порта {source_addr[0]}, извлечено {len(corrected_data)} байт данных (экземпляр 2).")
                except UnicodeDecodeError:
                    self.log_debug("Ошибка декодирования принятых данных (экземпляр 2).")
                except Exception as e:
                    self.log_debug(f"Ошибка обработки данных (экземпляр 2): {e}")
        except Exception as e:
            self.log_debug(f"Критическая ошибка в on_data_received_2: {e}")

    def send_data_1(self):
        """Готовит и отправляет данные из поля ввода экземпляра 1."""
        text_to_send = self.input_text.toPlainText().strip()
        if not text_to_send:
            return

        # Direct communication: always send text to instance 2 output as well with styling
        self.output_text_tab2.appendHtml(f"<span style='color: #009900; font-weight: bold;'>[Директ] {text_to_send}</span>")
        self.log_debug("Текст отправлен напрямую в окно вывода экземпляра 2 (прямая связь).")

        if self.port_tx_1 and self.port_tx_1.is_open:
            try:
                # Получаем номер порта из его имени (например, COM5 -> 5)
                port_num = int("".join(filter(str.isdigit, self.port_tx_1.name)))
            except (ValueError, TypeError):
                port_num = 0 # Значение по умолчанию, если имя порта не стандартное

            # Готовим данные
            frames, display_html = self.prepare_data(text_to_send, port_num)
            self.pre_send_data_window.setHtml(display_html)
            
            self.log_debug(f"Подготовлено {len(frames)} кадров для отправки.")

            try:
                # Отправляем кадры
                total_bytes_sent = 0
                for frame in frames:
                    self.port_tx_1.write(frame)
                    total_bytes_sent += len(frame)
                
                self.sent_bytes_count_1 += total_bytes_sent
                self.update_status_labels_1()
                self.log_debug(f"Успешно передано {total_bytes_sent} байт ({len(frames)} кадров).")

            except serial.SerialException as e:
                QMessageBox.critical(self, "Ошибка передачи", f"Не удалось отправить данные:\n{e}")
                self.log_debug(f"ОШИБКА ПЕРЕДАЧИ: {e}")
                self.disconnect_ports_1()

        self.input_text.setPlainText("")

    def send_data_2(self):
        """Готовит и отправляет данные из поля ввода экземпляра 2."""
        text_to_send = self.input_text_2.toPlainText().strip()
        if not text_to_send:
            return

        # Direct communication: always send text to instance 1 output as well with styling
        self.output_text.appendHtml(f"<span style='color: #009900; font-weight: bold;'>[Директ] {text_to_send}</span>")
        self.log_debug("Текст отправлен напрямую в окно вывода экземпляра 1 (прямая связь).")

        if self.port_tx_2 and self.port_tx_2.is_open:
            try:
                # Получаем номер порта из его имени (например, COM5 -> 5)
                port_num = int("".join(filter(str.isdigit, self.port_tx_2.name)))
            except (ValueError, TypeError):
                port_num = 0 # Значение по умолчанию, если имя порта не стандартное

            # Готовим данные
            frames, display_html = self.prepare_data(text_to_send, port_num)
            self.pre_send_data_window_2.setHtml(display_html)
            
            self.log_debug(f"Подготовлено {len(frames)} кадров для отправки (экземпляр 2).")

            try:
                # Отправляем кадры
                total_bytes_sent = 0
                for frame in frames:
                    self.port_tx_2.write(frame)
                    total_bytes_sent += len(frame)
                
                self.sent_bytes_count_2 += total_bytes_sent
                self.update_status_labels_2()
                self.log_debug(f"Успешно передано {total_bytes_sent} байт ({len(frames)} кадров) (экземпляр 2).")

            except serial.SerialException as e:
                QMessageBox.critical(self, "Ошибка передачи", f"Не удалось отправить данные:\n{e}")
                self.log_debug(f"ОШИБКА ПЕРЕДАЧИ (экземпляр 2): {e}")
                self.disconnect_ports_2()

        self.input_text_2.setPlainText("")

    def update_status_labels_1(self):
        """Обновляет информацию в окне состояния."""
        self.speed_status_label.setText(f"Скорость порта: {self.fixed_baud_rate}")
        self.sent_bytes_status_label.setText(f"Количество переданных байт: {self.sent_bytes_count_1}")

    def update_status_labels_2(self):
        """Обновляет информацию в окне состояния (экземпляр 2)."""
        self.speed_status_label_tab2.setText(f"Скорость порта: {self.fixed_baud_rate}")
        self.sent_bytes_status_label_tab2.setText(f"Количество переданных байт: {self.sent_bytes_count_2}")

    def toggle_controls_state_1(self, is_connected):
        """Включает/отключает элементы управления."""
        self.connect_button.setEnabled(not is_connected)
        self.disconnect_button.setEnabled(is_connected)
        self.port_combo.setEnabled(not is_connected)
        self.port_combo_2.setEnabled(not is_connected)
        self.parity_combo.setEnabled(not is_connected)

    def toggle_controls_state_2(self, is_connected):
        """Включает/отключает элементы управления (экземпляр 2)."""
        self.connect_button_tab2.setEnabled(not is_connected)
        self.disconnect_button_tab2.setEnabled(is_connected)
        self.port_combo_tab2.setEnabled(not is_connected)
        self.port_combo_2_tab2.setEnabled(not is_connected)
        self.parity_combo_tab2.setEnabled(not is_connected)

    def closeEvent(self, event):
        """Вызывается при закрытии окна для корректного завершения."""
        self.disconnect_ports_1()
        self.disconnect_ports_2()
        event.accept()

# --- Точка входа в приложение ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    if is_already_running():
        QMessageBox.critical(None, "Ошибка запуска", "Приложение уже запущено.\nПожалуйста, закройте другой экземпляр и попробуйте снова.")
        sys.exit(1)

    communicator = CommunicatorApp()
    communicator.show()

    sys.exit(app.exec())