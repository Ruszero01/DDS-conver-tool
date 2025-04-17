import os
import subprocess
import math
import threading
from PyQt5.QtCore import QDir, QPoint, QSettings, Qt, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDesktopWidget, QMainWindow, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QWidget, QFileDialog, QHBoxLayout, QVBoxLayout, QSizePolicy, QProgressBar
from PyQt5.QtGui import QIcon
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

# Initialize global variables
observer_running = False
observer = None
image_handler = None
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class ImageHandler(FileSystemEventHandler):
    def __init__(self, observer, delete_source, max_resolution, recursive):
        super().__init__()
        self.observer = observer
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.processed_files = {}
        self.lock = threading.Lock()
        self.delete_source = delete_source
        self.max_resolution = max_resolution
        self.recursive = recursive

    def start(self):
        self.observer.start()

    def stop(self):
        self.observer.stop()

    def set_delete_source(self, delete_source):
        self.delete_source = delete_source

    def set_max_resolution(self, max_resolution):
        self.max_resolution = max_resolution

    def set_recursive(self, recursive):
        self.recursive = recursive

    def on_modified(self, event):
        if event.is_directory:
            return

        if observer_running:
            image_path = event.src_path.lower()
            if image_path.endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                output_path = os.path.splitext(image_path)[0] + '.dds'
                if not os.path.exists(output_path) or os.path.getmtime(output_path) < os.path.getmtime(image_path):
                    self.executor.submit(self.process_image, image_path, output_path)

    def process_image(self, image_path, output_path):
        with self.lock:
            convert_and_resize_to_dds(image_path, output_path, self.delete_source, self.max_resolution)
            try:
                if self.delete_source:
                    os.remove(image_path)
            except PermissionError:
                pass

        if self.recursive and os.path.isdir(image_path):
            for root, dirs, files in os.walk(image_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                        output_file_path = os.path.splitext(file_path)[0] + '.dds'
                        if not os.path.exists(output_file_path) or os.path.getmtime(output_file_path) < os.path.getmtime(file_path):
                            self.executor.submit(self.process_image, file_path, output_file_path)

    def on_created(self, event):
        if event.is_directory:
            if self.recursive:
                self.on_modified(event)

def has_alpha(image):
    return image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)

def is_single_channel(image):
    return image.mode in ('L', '1') 

def convert_and_resize_to_dds(input_path, output_path, delete_source, max_resolution):
    try:
        image = Image.open(input_path)
    except FileNotFoundError:
        print(f"---------Complete---------")
        return
    except Exception as e:
        print(f"Error opening image {input_path}: {e}")
        return
    
    new_width = math.ceil(image.width / 4) * 4
    new_height = math.ceil(image.height / 4) * 4

    if image.width == image.height:
        max_size = max_resolution
        if new_width > max_size:
            scale_factor = max_size / new_width
            new_width = max_size
            new_height = int(new_height * scale_factor)

    if is_single_channel(image):
        if has_alpha(image):
            image = image.convert("RGBA")
        else:
            image = image.convert("RGB")

    # 添加判断条件，如果图片没有 alpha 通道并且分辨率大于 4096，则使用 BC7 格式进行压缩
    if not has_alpha(image) and (new_width > 4096 or new_height > 4096):
        compression_arg = '-bc7'
    else:
        compression_arg = '-bc1' if is_single_channel(image) else '-bc3' if has_alpha(image) else '-bc1'

    resized_image = image.resize((new_width, new_height), resample=Image.BILINEAR)

    try:
        temp_path = output_path + "_temp.dds"
        resized_image.save(temp_path)
        nvcompress_path = os.path.join(script_dir, 'bin/nvcompress.exe')
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen([nvcompress_path, compression_arg, temp_path, output_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        stdout, stderr = process.communicate()
        if stderr:
            print(stderr.decode())
        os.remove(temp_path)
        print(f"Converted {input_path} to {output_path} using {compression_arg}")

        if delete_source:
            os.remove(input_path)
    except Exception as e:
        print(f"Error converting {input_path} to {output_path}: {e}")


class ImageConverter(QObject):
    progress_changed = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, folder_path, delete_source, max_resolution, recursive):
        super().__init__()
        self.folder_path = folder_path
        self.delete_source = delete_source
        self.max_resolution = max_resolution
        self.recursive = recursive

    def convert_images(self):
        total_files = self.get_total_files(self.folder_path)
        converted_files = 0

        if self.recursive:
            for root, dirs, files in os.walk(self.folder_path):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                        image_path = os.path.join(root, file)
                        output_path = os.path.splitext(image_path)[0] + '.dds'
                        convert_and_resize_to_dds(image_path, output_path, self.delete_source, self.max_resolution)
                        converted_files += 1
                        progress = int((converted_files / total_files) * 100)
                        self.progress_changed.emit(progress)
        else:
            for file in os.listdir(self.folder_path):
                image_path = os.path.join(self.folder_path, file)
                if os.path.isfile(image_path) and file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    output_path = os.path.splitext(image_path)[0] + '.dds'
                    convert_and_resize_to_dds(image_path, output_path, self.delete_source, self.max_resolution)
                    converted_files += 1
                    progress = int((converted_files / total_files) * 100)
                    self.progress_changed.emit(progress)

        self.finished.emit()

    def get_total_files(self, folder_path):
        if self.recursive:
            total_files = sum(len(files) for _, _, files in os.walk(folder_path))
        else:
            total_files = len([file for file in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, file))])
        return total_files

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DDSTool v1.0")
        self.adjustSize()
        self.settings = QSettings("YourOrganization", "DDSTool")           
        self.restoreGeometry(self.settings.value("geometry", self.saveGeometry()))
        # self.restoreState(self.settings.value("windowState", self.saveState()))
        if not self.settings.contains("geometry"):
            self.center_window()

        self.last_folder_path = self.settings.value("last_folder_path", QDir.homePath())
        self.setWindowIcon(QIcon(os.path.join(script_dir, "assets/icon.ico"))) # 设置窗口图标

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        self.row1_layout = QHBoxLayout()
        self.layout.addLayout(self.row1_layout)

        # self.current_folder_label = QLabel("文件路径:")
        # self.row1_layout.addWidget(self.current_folder_label)

        self.current_folder_entry = QLineEdit()
        self.current_folder_entry.setReadOnly(True)
        self.row1_layout.addWidget(self.current_folder_entry)

        self.select_button = QPushButton("选择")
        self.select_button.setIcon(QIcon(os.path.join(script_dir, "assets/select.png"))) # 设置按钮图标
        self.select_button.clicked.connect(self.select_folder)
        self.row1_layout.addWidget(self.select_button)

        self.open_button = QPushButton("打开")
        self.open_button.setIcon(QIcon(os.path.join(script_dir, "assets/open.png"))) # 设置按钮图标
        self.open_button.clicked.connect(self.open_folder)
        self.row1_layout.addWidget(self.open_button)

        self.row2_layout = QHBoxLayout()
        self.layout.addLayout(self.row2_layout)

        self.start_button = QPushButton("开始")
        icon_path = os.path.join(script_dir, "assets", "watch.png")
        self.start_button.setIcon(QIcon(icon_path)) # 设置按钮图标
        self.start_button.clicked.connect(self.toggle_observer)
        self.row2_layout.addWidget(self.start_button)

        self.convert_button = QPushButton("转换")
        self.convert_button.setIcon(QIcon(os.path.join(script_dir, "assets/convert.png"))) # 设置按钮图标
        self.convert_button.clicked.connect(self.convert_images)
        self.row2_layout.addWidget(self.convert_button)

        self.options_layout = QHBoxLayout()
        self.layout.addLayout(self.options_layout)

        self.max_resolution_label = QLabel("方形纹理最大分辨率:")
        self.options_layout.addWidget(self.max_resolution_label)

        self.max_resolution_dropdown = QComboBox()
        self.max_resolution_dropdown.addItems(["512", "1024", "2048"])
        self.max_resolution_dropdown.setCurrentText("1024")
        self.options_layout.addWidget(self.max_resolution_dropdown, alignment=Qt.AlignLeft)

        self.recursive_checkbox = QCheckBox("包含子目录")
        self.options_layout.addWidget(self.recursive_checkbox)

        self.delete_source_checkbox = QCheckBox("删除源文件")
        self.options_layout.addWidget(self.delete_source_checkbox)

        self.progress = QProgressBar()
        self.layout.addWidget(self.progress)

        self.observer = None
        self.image_handler = None

        self.delete_source_checkbox.stateChanged.connect(self.update_image_handler_settings)
        self.recursive_checkbox.stateChanged.connect(self.update_image_handler_settings)

        self.progress.hide()
        self.converter_thread = QThread()
        self.image_converter = ImageConverter("", False, 1024, False)
        self.image_converter.moveToThread(self.converter_thread)
        self.converter_thread.finished.connect(self.converter_thread.deleteLater)
        self.progress.setFixedHeight(18)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
                background-color: #f0f0f0;
                text-align: center; /* 居中显示文本 */
            }
            QProgressBar::chunk {
                background-color: #37c9e1;
                width: 10px;
            }
            QProgressBar::chunk:disabled {
                background-color: #a0a0a0; /* 禁用时的颜色 */
            }
            QProgressBar::chunk:disabled::chunk {
                background-color: #a0a0a0;
            }
            QProgressBar::chunk:disabled {
                border-radius: 0px; /* 禁用时取消圆角 */
            }
            QProgressBar::chunk:disabled::chunk {
                border-radius: 0px;
            }                             
        """)        

    def update_image_handler_settings(self):
        delete_source = self.delete_source_checkbox.isChecked()
        max_resolution = int(self.max_resolution_dropdown.currentText())
        recursive = self.recursive_checkbox.isChecked()

        if self.image_handler is None:
            self.image_handler = ImageHandler(None, delete_source, max_resolution, recursive)
        else:
            self.image_handler.set_delete_source(delete_source)
            self.image_handler.set_max_resolution(max_resolution)
            self.image_handler.set_recursive(recursive)

        if observer_running:
            folder_path = self.current_folder_entry.text()
            self.observer.unschedule_all()
            self.observer.schedule(self.image_handler, folder_path, recursive=recursive)

    def select_folder(self):
        global observer_running

        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹", self.last_folder_path)
        if folder_path:
            self.current_folder_entry.setText(folder_path)
            self.settings.setValue("last_folder_path", folder_path)

            if observer_running:  # 如果监视状态为活动状态
                self.toggle_observer()  # 先停止监视
                self.toggle_observer()  # 然后重新启动监视

    def open_folder(self):
        folder_path = self.current_folder_entry.text()
        if folder_path and os.path.exists(folder_path):
            os.startfile(folder_path)

    def toggle_observer(self):
        global observer_running

        folder_path = self.current_folder_entry.text()
        if not folder_path:
            print("请先选择文件夹路径。")
            return

        if observer_running:
            self.observer.stop()
            observer_running = False
            self.start_button.setText("开始")
            self.start_button.setIcon(QIcon(os.path.join(script_dir, "assets", "watch.png")))
            self.start_button.setStyleSheet("")
        else:
            delete_source = self.delete_source_checkbox.isChecked()
            max_resolution = int(self.max_resolution_dropdown.currentText())
            recursive = self.recursive_checkbox.isChecked()

            if self.observer is None:
                self.observer = Observer()
            else:
                self.observer.stop()
                self.observer = Observer()

            self.image_handler = ImageHandler(self.observer, delete_source, max_resolution, recursive)
            self.observer.schedule(self.image_handler, folder_path, recursive=recursive)
            self.image_handler.start()

            observer_running = True
            self.start_button.setText("停止")
            self.start_button.setIcon(QIcon(os.path.join(script_dir, "assets/stop.png")))
            self.start_button.setStyleSheet("background-color: orange")

    def convert_images(self):
        folder_path = self.current_folder_entry.text()
        if folder_path and os.path.exists(folder_path):
            # 如果之前有转换线程正在运行，先停止它
            if hasattr(self, 'converter_thread') and self.converter_thread.isRunning():
                self.converter_thread.quit()
                self.converter_thread.wait()

            delete_source = self.delete_source_checkbox.isChecked()
            max_resolution = int(self.max_resolution_dropdown.currentText())
            recursive = self.recursive_checkbox.isChecked()

            # 创建新的 ImageConverter 对象
            self.image_converter = ImageConverter(folder_path, delete_source, max_resolution, recursive)

            # 创建新的转换线程
            self.converter_thread = QThread()
            self.image_converter.moveToThread(self.converter_thread)
            self.converter_thread.started.connect(self.image_converter.convert_images)
            self.image_converter.progress_changed.connect(self.update_progress)
            self.image_converter.finished.connect(self.converter_finished)

            # 启动转换线程
            self.converter_thread.start()

            # 转换开始时显示进度条
            self.progress.show()
        
    def update_progress(self, progress):
        self.progress.setValue(progress)

    def converter_finished(self):
        # 转换完成后重置进度条
        self.progress.setValue(0)
        self.progress.hide()

    def center_window(self):
        screen = QDesktopWidget().screenGeometry()
        window_size = self.geometry()
        center_point = screen.center() - QPoint(int(window_size.width() / 2), int(window_size.height() / 2))
        self.move(center_point)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        super().closeEvent(event)

def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec_()

if __name__ == "__main__":
    main()
