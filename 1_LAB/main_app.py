import sys
import os
import serial
import serial.tools.list_ports
import threading
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget, QHBoxLayout
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

        self.setWindowTitle("COM Communicator")

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
        self.input_line.returnPressed.connect(self.send_data_1)
        
        self.connect_button_tab2.clicked.connect(self.connect_ports_2)
        self.disconnect_button_tab2.clicked.connect(self.disconnect_ports_2)
        self.input_line_tab2.returnPressed.connect(self.send_data_2)
        
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
        self.debug_text.appendPlainText(f"[{timestamp}] {message}")

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
        """Слот для обработки принятых байтов, буферизации и отображения в окне вывода."""
        self.rx_buffer_1.extend(data_bytes)

        # Обрабатываем все полные строки в буфере
        while b'\n' in self.rx_buffer_1:
            line, self.rx_buffer_1 = self.rx_buffer_1.split(b'\n', 1)
            try:
                # Декодируем строку и добавляем в виджет. appendPlainText добавляет новую строку.
                text = line.decode('utf-8', errors='ignore')
                self.output_text.appendPlainText(text)
            except Exception as e:
                self.log_debug(f"Ошибка декодирования: {e}")

    def on_data_received_2(self, data_bytes):
        """Слот для обработки принятых байтов и отображения в окне вывода (экземпляр 2)."""
        self.rx_buffer_2.extend(data_bytes)

        # Обрабатываем все полные строки в буфере
        while b'\n' in self.rx_buffer_2:
            line, self.rx_buffer_2 = self.rx_buffer_2.split(b'\n', 1)
            try:
                # Декодируем строку и добавляем в виджет. appendPlainText добавляет новую строку.
                text = line.decode('utf-8', errors='ignore')
                self.output_text_tab2.appendPlainText(text)
            except Exception as e:
                self.log_debug(f"Ошибка декодирования (экземпляр 2): {e}")

    def send_data_1(self):
        """Отправляет данные из поля ввода и дублирует в вывод второй вкладки."""
        text_to_send = self.input_line.text()
        if self.port_tx_1 and self.port_tx_1.is_open:
            self.log_debug(f"Попытка отправки: '{text_to_send}'")
            try:
                # Передаем посимвольно
                for char in text_to_send + '\n':
                    byte = char.encode('utf-8')
                    self.port_tx_1.write(byte)
                    self.sent_bytes_count_1 += 1
                
                self.update_status_labels_1()
                self.log_debug(f"Успешно передано {len(text_to_send) + 1} байт.")
                # Дублируем вывод во вторую вкладку
                self.output_text_tab2.appendPlainText(f"(from 1): {text_to_send}")

            except serial.SerialException as e:
                QMessageBox.critical(self, "Ошибка передачи", f"Не удалось отправить данные:\n{e}")
                self.log_debug(f"ОШИБКА ПЕРЕДАЧИ: {e}")
                self.disconnect_ports_1()
        else:
             # Даже если порт не подключен, дублируем
             self.output_text_tab2.appendPlainText(f"(from 1, no connection): {text_to_send}")

        self.input_line.clear()

    def send_data_2(self):
        """Отправляет данные из поля ввода (экземпляр 2) и дублирует в вывод первой вкладки."""
        text_to_send = self.input_line_tab2.text()
        if self.port_tx_2 and self.port_tx_2.is_open:
            self.log_debug(f"Попытка отправки (экземпляр 2): '{text_to_send}'")
            try:
                # Передаем посимвольно
                for char in text_to_send + '\n':
                    byte = char.encode('utf-8')
                    self.port_tx_2.write(byte)
                    self.sent_bytes_count_2 += 1
                
                self.update_status_labels_2()
                self.log_debug(f"Успешно передано {len(text_to_send) + 1} байт (экземпляр 2).")
                # Дублируем вывод в первую вкладку
                self.output_text.appendPlainText(f"(from 2): {text_to_send}")

            except serial.SerialException as e:
                QMessageBox.critical(self, "Ошибка передачи", f"Не удалось отправить данные:\n{e}")
                self.log_debug(f"ОШИБКА ПЕРЕДАЧИ (экземпляр 2): {e}")
                self.disconnect_ports_2()
        else:
            # Даже если порт не подключен, дублируем
            self.output_text.appendPlainText(f"(from 2, no connection): {text_to_send}")

        self.input_line_tab2.clear()

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
