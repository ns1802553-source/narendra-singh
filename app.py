import os
import sys
import cv2
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QListWidget, QComboBox,
    QCheckBox, QProgressBar, QMessageBox, QFrame
)

APP_NAME = "RepliCut AI"


def bundled_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", str(Path(__file__).parent))
    candidate = Path(base) / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} was not found. Reinstall the packaged app.")


def detect_scene_durations(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("The reference video could not be opened.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    total_duration = total_frames / fps if total_frames else 0
    if total_duration <= 0:
        cap.release()
        raise RuntimeError("The reference video has no readable duration.")

    cuts = [0.0]
    previous = None
    frame_index = 0
    sample_every = max(1, int(fps // 3))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_index % sample_every == 0:
            small = cv2.resize(frame, (96, 54))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if previous is not None:
                difference = float(cv2.absdiff(gray, previous).mean())
                if difference > 28 and (frame_index / fps - cuts[-1]) > 0.45:
                    cuts.append(frame_index / fps)
            previous = gray
        frame_index += 1
    cap.release()
    cuts.append(total_duration)
    durations = [round(b - a, 3) for a, b in zip(cuts, cuts[1:]) if b - a >= 0.35]
    if not durations:
        durations = [round(min(total_duration, 3.0), 3)]
    return durations


def render_video(reference: str, raw_files: list[str], output: str, size: str,
                 use_reference_audio: bool, progress_callback):
    if not raw_files:
        raise RuntimeError("Add at least one raw video clip.")
    ffmpeg = bundled_path("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    durations = detect_scene_durations(reference)
    width, height = (1440, 2560) if size == "Vertical 2K" else (2560, 1440)

    # Use raw clips in upload order; repeat them if the reference has more detected scenes.
    selected = [raw_files[i % len(raw_files)] for i in range(len(durations))]
    with tempfile.TemporaryDirectory(prefix="replicut_") as temp_dir:
        pieces = []
        for i, (clip, duration) in enumerate(zip(selected, durations)):
            piece = str(Path(temp_dir) / f"part_{i:04d}.mp4")
            cmd = [
                ffmpeg, "-y", "-i", clip, "-t", str(duration),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30,setsar=1",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-pix_fmt", "yuv420p", piece
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                raise RuntimeError("A raw clip could not be processed:\n" + result.stderr[-1800:])
            pieces.append(piece)
            progress_callback(int((i + 1) / (len(durations) + 1) * 85))

        concat_file = str(Path(temp_dir) / "concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for piece in pieces:
                safe = piece.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        concat_cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file]
        if use_reference_audio:
            concat_cmd += ["-i", reference, "-map", "0:v:0", "-map", "1:a:0?"]
        concat_cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", output]
        result = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            # Retry without audio if the reference has no audio stream.
            if use_reference_audio:
                retry = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
                         "-c:v", "copy", output]
                result = subprocess.run(retry, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                raise RuntimeError("Final export failed:\n" + result.stderr[-1800:])
    progress_callback(100)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RepliCut AI — Video Editor")
        self.setMinimumSize(820, 650)
        self.reference = ""
        self.raw_files = []
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("RepliCut AI")
        title.setObjectName("title")
        subtitle = QLabel("Reference-guided video editing • Windows MVP")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.ref_label = QLabel("No reference video selected")
        self.ref_label.setObjectName("fileLabel")
        ref_row = QHBoxLayout()
        ref_button = QPushButton("Choose Reference Video")
        ref_button.clicked.connect(self.choose_reference)
        ref_row.addWidget(ref_button)
        ref_row.addWidget(self.ref_label, 1)
        layout.addLayout(ref_row)

        raw_title = QLabel("Your raw footage")
        raw_title.setObjectName("section")
        layout.addWidget(raw_title)
        raw_row = QHBoxLayout()
        add_button = QPushButton("Add Raw Videos")
        add_button.clicked.connect(self.add_raw)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_selected)
        raw_row.addWidget(add_button)
        raw_row.addWidget(remove_button)
        raw_row.addStretch(1)
        layout.addLayout(raw_row)
        self.raw_list = QListWidget()
        self.raw_list.setMinimumHeight(170)
        layout.addWidget(self.raw_list)

        options = QHBoxLayout()
        options.addWidget(QLabel("Export format"))
        self.size_box = QComboBox()
        self.size_box.addItems(["Vertical 2K", "Horizontal 2K"])
        options.addWidget(self.size_box)
        self.audio_check = QCheckBox("Use audio from reference video")
        self.audio_check.setChecked(True)
        options.addWidget(self.audio_check)
        options.addStretch(1)
        layout.addLayout(options)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Ready. Add a reference video and your raw footage.")
        self.status.setObjectName("subtitle")
        layout.addWidget(self.status)

        self.generate = QPushButton("GENERATE VIDEO")
        self.generate.setObjectName("generate")
        self.generate.setMinimumHeight(54)
        self.generate.clicked.connect(self.generate_video)
        layout.addWidget(self.generate)

        note = QLabel("Note: This first build detects approximate cuts and assembles your clips in upload order. It does not yet recreate every effect or intelligently understand each shot.")
        note.setWordWrap(True)
        note.setObjectName("note")
        layout.addWidget(note)

        self.setStyleSheet("""
            QMainWindow, QWidget { background: #10131b; color: #f4f6fb; font-family: Segoe UI; font-size: 14px; }
            QLabel#title { font-size: 32px; font-weight: 800; color: #ffffff; }
            QLabel#subtitle { color: #9ca8bb; font-size: 13px; }
            QLabel#section { font-size: 18px; font-weight: 700; margin-top: 8px; }
            QLabel#fileLabel { color: #b7c3d8; }
            QLabel#note { color: #9ca8bb; font-size: 12px; }
            QPushButton { background: #252d3d; border: 1px solid #3a465c; border-radius: 9px; padding: 11px 16px; font-weight: 600; }
            QPushButton:hover { background: #303b50; }
            QPushButton#generate { background: #27b36a; color: #06150d; border: 0; font-size: 16px; font-weight: 800; }
            QListWidget { background: #171d29; border: 1px solid #30394a; border-radius: 9px; padding: 8px; }
            QComboBox { background: #202838; border: 1px solid #3a465c; border-radius: 7px; padding: 8px; min-width: 140px; }
            QProgressBar { border: 1px solid #3a465c; border-radius: 7px; background: #202838; height: 18px; text-align: center; }
            QProgressBar::chunk { background: #27b36a; border-radius: 6px; }
            QCheckBox { color: #cbd4e2; spacing: 7px; }
        """)

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose reference video", "", "Videos (*.mp4 *.mov *.mkv *.avi)")
        if path:
            self.reference = path
            self.ref_label.setText(Path(path).name)

    def add_raw(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose raw footage", "", "Videos (*.mp4 *.mov *.mkv *.avi)")
        for path in paths:
            if path not in self.raw_files:
                self.raw_files.append(path)
                self.raw_list.addItem(path)

    def remove_selected(self):
        for item in self.raw_list.selectedItems():
            path = item.text()
            if path in self.raw_files:
                self.raw_files.remove(path)
            self.raw_list.takeItem(self.raw_list.row(item))

    def generate_video(self):
        if not self.reference:
            QMessageBox.warning(self, APP_NAME, "Please choose a reference video first.")
            return
        if not self.raw_files:
            QMessageBox.warning(self, APP_NAME, "Please add at least one raw video.")
            return
        output, _ = QFileDialog.getSaveFileName(self, "Save finished video", "RepliCut_Output.mp4", "MP4 Video (*.mp4)")
        if not output:
            return
        self.generate.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Analyzing reference and assembling footage…")
        QApplication.processEvents()
        try:
            render_video(self.reference, self.raw_files, output, self.size_box.currentText(),
                         self.audio_check.isChecked(), self.progress.setValue)
            self.status.setText("Export complete.")
            QMessageBox.information(self, APP_NAME, f"Your video is ready:\n{output}")
        except Exception as exc:
            self.status.setText("Export failed.")
            QMessageBox.critical(self, APP_NAME, str(exc))
        finally:
            self.generate.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
