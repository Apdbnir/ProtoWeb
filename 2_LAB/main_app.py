import sys
import os
import serial
import serial.tools.list_ports
import threading
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import pyqtSignal, QObject, QThread

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

        self.setWindowTitle("COM Communicator - Улучшенная версия")
        
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
        self.FCS = b'\x00'        # Always 0 as per requirements
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

    def prepare_data(self, text_data, source_port_num):
        """
        Подготавливает данные для отправки: разбивает на кадры,
        дополняет нулями, выполняет байт-стаффинг.
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

            # 3. Байт-стаффинг
            stuffed_chunk = bytearray()
            stuffed_indices = set()
            for byte_index, byte in enumerate(chunk):
                byte = bytes([byte])
                if byte in self.STUFF_MAP:
                    stuffed_chunk.extend(self.STUFF_MAP[byte])
                    # Запоминаем индекс, где произошел стаффинг
                    stuffed_indices.add(len(stuffed_chunk) - 2)
                    stuffed_indices.add(len(stuffed_chunk) - 1)
                else:
                    stuffed_chunk.extend(byte)
            
            # 4. Сборка кадра в правильном порядке:
            # Flag (2 байта) + Source Address (1 байт) + Destination Address (1 байт) + Data (N+1 байт) + FCS (1 байт)
            frame = self.FLAG + source_addr + self.DEST_ADDR + stuffed_chunk + self.FCS
            prepared_frames.append(frame)

            # 5. Формирование строки для отображения с правильным порядком
            display_html += f"<div style='margin: 2px 0;'><b>Кадр {i+1}:</b> "
            display_html += f"<span style='color: #009900; font-weight: bold;'>{self.FLAG.hex().upper()}</span> "  # Flag: 2 байта (green)
            display_html += f"<span style='color: #CCCC00;'>{source_addr.hex().upper()}</span> "  # Source Address: 1 байт (yellow)
            display_html += f"<span style='color: grey;'>{self.DEST_ADDR.hex().upper()}</span> "  # Destination Address: 1 байт
            
            # Отображение данных с подсветкой
            stuffed_hex = ""
            byte_pos = 0
            for byte in stuffed_chunk:
                if byte_pos in stuffed_indices:
                    stuffed_hex += f"<span style='color: red; font-weight: bold;'>{byte:02X}</span> "  # Подсвечиваем байты после стаффинга
                else:
                    stuffed_hex += f"{byte:02X} "
                byte_pos += 1
            display_html += stuffed_hex
            
            display_html += f"<span style='color: grey;'>{self.FCS.hex().upper()}</span>"  # FCS: 1 байт
            display_html += "</div>"

        return prepared_frames, display_html


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

                # Проверяем, достаточно ли данных для минимального кадра:
                # FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS(1) = 15 байт
                if len(self.rx_buffer_1) - start_index < 15:
                    # Недостаточно данных для полного кадра, ждем больше
                    return

                # Извлекаем потенциальный кадр
                potential_frame = self.rx_buffer_1[start_index:start_index + 15]
                
                # Извлекаем фиксированные поля
                source_addr = potential_frame[2:3]
                dest_addr = potential_frame[3:4]
                
                # Извлекаем 10 байт данных (ожидаем фиксированную длину)
                raw_data = potential_frame[4:14]
                
                # Извлекаем FCS
                fcs = potential_frame[14:15]
                
                # Выполняем де-стаффинг данных
                unstuffed_data = bytearray()
                i = 0
                while i < len(raw_data):
                    # Проверяем, есть ли достаточно байт для проверки последовательности из 2 байт
                    if i + 1 < len(raw_data):
                        sequence = bytes(raw_data[i:i+2])  # Convert to bytes for dictionary lookup
                        if sequence in self.UNSTUFF_MAP:
                            unstuffed_data.extend(self.UNSTUFF_MAP[sequence])
                            i += 2
                        else:
                            unstuffed_data.extend(bytes([raw_data[i]]))
                            i += 1
                    else:
                        # Только один байт остался
                        unstuffed_data.extend(bytes([raw_data[i]]))
                        i += 1

                # Удаляем обработанный кадр из буфера
                next_frame_start = start_index + 15  # Длина кадра: FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS(1)
                if next_frame_start <= len(self.rx_buffer_1):
                    self.rx_buffer_1 = self.rx_buffer_1[next_frame_start:]
                else:
                    self.rx_buffer_1 = bytearray()  # Очищаем, если что-то пошло не так

                # Обработка данных
                try:
                    cleaned_payload = unstuffed_data.rstrip(b'\x00')
                    text = cleaned_payload.decode('utf-8', errors='replace')
                    # Add received packet data with different styling
                    self.output_text_tab2.appendHtml(f"<span style='color: #CCCC00; font-style: italic;'>[Пакет] {text}</span>")
                    self.log_debug(f"Принят и обработан кадр от порта {source_addr[0]}, извлечено {len(unstuffed_data)} байт данных.")
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

                # Проверяем, достаточно ли данных для минимального кадра:
                # FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS(1) = 15 байт
                if len(self.rx_buffer_2) - start_index < 15:
                    # Недостаточно данных для полного кадра, ждем больше
                    return

                # Извлекаем потенциальный кадр
                potential_frame = self.rx_buffer_2[start_index:start_index + 15]
                
                # Извлекаем фиксированные поля
                source_addr = potential_frame[2:3]
                dest_addr = potential_frame[3:4]
                
                # Извлекаем 10 байт данных (ожидаем фиксированную длину)
                raw_data = potential_frame[4:14]
                
                # Извлекаем FCS
                fcs = potential_frame[14:15]
                
                # Выполняем де-стаффинг данных
                unstuffed_data = bytearray()
                i = 0
                while i < len(raw_data):
                    # Проверяем, есть ли достаточно байт для проверки последовательности из 2 байт
                    if i + 1 < len(raw_data):
                        sequence = bytes(raw_data[i:i+2])  # Convert to bytes for dictionary lookup
                        if sequence in self.UNSTUFF_MAP:
                            unstuffed_data.extend(self.UNSTUFF_MAP[sequence])
                            i += 2
                        else:
                            unstuffed_data.extend(bytes([raw_data[i]]))
                            i += 1
                    else:
                        # Только один байт остался
                        unstuffed_data.extend(bytes([raw_data[i]]))
                        i += 1

                # Удаляем обработанный кадр из буфера
                next_frame_start = start_index + 15  # Длина кадра: FLAG(2) + SA(1) + DA(1) + DATA(10) + FCS(1)
                if next_frame_start <= len(self.rx_buffer_2):
                    self.rx_buffer_2 = self.rx_buffer_2[next_frame_start:]
                else:
                    self.rx_buffer_2 = bytearray()  # Очищаем, если что-то пошло не так

                # Обработка данных
                try:
                    cleaned_payload = unstuffed_data.rstrip(b'\x00')
                    text = cleaned_payload.decode('utf-8', errors='replace')
                    # Add received packet data with different styling
                    self.output_text.appendHtml(f"<span style='color: #CCCC00; font-style: italic;'>[Пакет] {text}</span>")
                    self.log_debug(f"Принят и обработан кадр от порта {source_addr[0]}, извлечено {len(unstuffed_data)} байт данных (экземпляр 2).")
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
