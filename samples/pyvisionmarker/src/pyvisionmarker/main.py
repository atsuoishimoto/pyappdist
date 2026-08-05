"""Vision Inspector -- a local object-detection desktop app.

Copyright (C) 2026 pyappdist sample authors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License version 3 as published by the Free
Software Foundation. See the LICENSE file for the full text.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
import urllib.request
from typing import Any

import gradio as gr
import torch
import webview
from PIL import Image
from transformers import pipeline


# ============================================================
# Application settings
# ============================================================

APP_TITLE = "Vision Inspector"

HOST = "127.0.0.1"
PORT = 7860
APP_URL = f"http://{HOST}:{PORT}"

DETECTION_MODEL_ID = "facebook/detr-resnet-50"

# Label of the annotated image. Doubles as a status line while the model loads.
DETECTION_LABEL = "Detection result"

MODEL_LOCK = threading.Lock()

detection_pipeline = None


# ============================================================
# Model loading
# ============================================================

def get_device() -> int:
    """
    Device setting for the transformers pipeline.

    Returns 0 (GPU) when CUDA is available, otherwise -1 (CPU).
    """
    if torch.cuda.is_available():
        return 0

    return -1


def load_detection_model():
    """
    Load the model on the first analysis only.
    Later calls reuse the model already held in memory.
    """
    global detection_pipeline

    if detection_pipeline is not None:
        return detection_pipeline

    with MODEL_LOCK:
        # Re-check: another thread may have finished loading already
        if detection_pipeline is not None:
            return detection_pipeline

        print(f"Loading object detection model: {DETECTION_MODEL_ID}")

        detection_pipeline = pipeline(
            task="object-detection",
            model=DETECTION_MODEL_ID,
            device=get_device(),
        )

        print("Model loaded.")

    return detection_pipeline


# ============================================================
# Object detection
# ============================================================

def detect_objects(
    image: Image.Image,
    detector,
    threshold: float,
) -> tuple[
    tuple[Image.Image, list[tuple[tuple[int, int, int, int], str]]],
    list[dict[str, Any]],
]:
    """
    Run DETR object detection and convert the predictions into the
    shape expected by Gradio's AnnotatedImage component.
    """
    predictions = detector(
        image,
        threshold=threshold,
    )

    annotations: list[
        tuple[tuple[int, int, int, int], str]
    ] = []

    detection_results: list[dict[str, Any]] = []

    for prediction in predictions:
        box = prediction["box"]

        xmin = int(box["xmin"])
        ymin = int(box["ymin"])
        xmax = int(box["xmax"])
        ymax = int(box["ymax"])

        label = str(prediction["label"])
        score = float(prediction["score"])

        display_label = f"{label} {score:.0%}"

        annotations.append(
            (
                (xmin, ymin, xmax, ymax),
                display_label,
            )
        )

        detection_results.append(
            {
                "label": label,
                "score": round(score, 4),
                "box": {
                    "xmin": xmin,
                    "ymin": ymin,
                    "xmax": xmax,
                    "ymax": ymax,
                },
            }
        )

    annotated_image = (
        image,
        annotations,
    )

    return annotated_image, detection_results


# ============================================================
# Markdown rendering for the UI
# ============================================================

def escape_markdown_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_detection_markdown(
    detections: list[dict[str, Any]],
) -> str:
    detection_lines = []

    for item in detections:
        detection_lines.append(
            "| "
            f"{escape_markdown_table(item['label'])} | "
            f"{item['score']:.1%} | "
            f"{item['box']['xmin']}, {item['box']['ymin']}, "
            f"{item['box']['xmax']}, {item['box']['ymax']} |"
        )

    if detection_lines:
        detection_table = "\n".join(
            [
                "| Object | Score | Box xmin, ymin, xmax, ymax |",
                "|---|---:|---|",
                *detection_lines,
            ]
        )
    else:
        detection_table = "No objects were detected above the current threshold."

    return f"""
# Detection results

{detection_table}
"""


# ============================================================
# Analysis entry point
# ============================================================

def analyze_image(
    image: Image.Image | None,
    detection_threshold: float,
):
    if image is None:
        raise gr.Error("Select an image to analyze.")

    try:
        image = image.convert("RGB")

        if detection_pipeline is None:
            # First run only. Fetching and initialising the model takes long
            # enough that the UI has to say what it is waiting for. Reading the
            # global without the lock can only cost one redundant message.
            yield (
                gr.update(
                    label=f"Loading the detection model: {DETECTION_MODEL_ID}"
                ),
                gr.skip(),
            )

        detector = load_detection_model()

        annotated_image, detections = detect_objects(
            image=image,
            detector=detector,
            threshold=float(detection_threshold),
        )

        yield (
            gr.update(value=annotated_image, label=DETECTION_LABEL),
            build_detection_markdown(detections),
        )

    except Exception as exception:
        traceback.print_exc()

        raise gr.Error(
            f"Image analysis failed: {exception}"
        ) from exception


# ============================================================
# Gradio UI
# ============================================================

CUSTOM_CSS = """
:root {
    --background: #090b12;
    --panel: rgba(21, 25, 39, 0.88);
    --border: rgba(255, 255, 255, 0.09);
    --text: #f3f5fb;
    --muted: #979db0;
    --accent: #7c6cff;
    --accent-2: #3ac7ff;
}

html,
body {
    background: var(--background);
}

.gradio-container {
    max-width: 100% !important;
    min-height: 100vh !important;
    margin: 0 !important;
    padding: 24px !important;
    background:
        radial-gradient(
            circle at 10% 0%,
            rgba(94, 76, 255, 0.22),
            transparent 35%
        ),
        radial-gradient(
            circle at 100% 20%,
            rgba(40, 173, 255, 0.16),
            transparent 32%
        ),
        #090b12;
    color: var(--text);
}

.app-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18px;
    padding: 4px 6px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 14px;
}

.brand-icon {
    width: 42px;
    height: 42px;
    border-radius: 13px;
    display: grid;
    place-items: center;
    font-size: 21px;
    background:
        linear-gradient(
            135deg,
            var(--accent),
            var(--accent-2)
        );
    box-shadow: 0 10px 32px rgba(80, 92, 255, 0.34);
}

.brand-title {
    font-size: 20px;
    font-weight: 750;
    letter-spacing: 0.02em;
}

.brand-subtitle {
    color: var(--muted);
    font-size: 12px;
    margin-top: 2px;
}

.status-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.04);
    color: #c5cad8;
    font-size: 12px;
}

.status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #44d69c;
    box-shadow: 0 0 12px rgba(68, 214, 156, 0.8);
}

/*
 * Not named "panel": Gradio reserves that class for Column(variant="panel")
 * and silently drops it from elem_classes.
 */
.app-panel {
    border: 1px solid var(--border) !important;
    border-radius: 18px !important;
    background: var(--panel) !important;
    box-shadow:
        0 18px 55px rgba(0, 0, 0, 0.24),
        inset 0 1px 0 rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(18px);
    padding: 16px !important;
}

/*
 * Row(equal_height=True) puts flex: 1 0 auto on every block inside a column,
 * which inflates headings and pushes the two images out of alignment. Keep
 * the columns equal but let each block stay its natural height.
 */
.app-panel > * {
    flex-grow: 0 !important;
}

.primary-button {
    min-height: 46px !important;
    padding: 0 22px !important;
    border: 1px solid rgba(255, 255, 255, 0.14) !important;
    border-radius: 10px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    color: #ffffff !important;
    background: var(--accent) !important;
    box-shadow:
        0 1px 2px rgba(0, 0, 0, 0.4),
        inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
    transition:
        background 0.15s ease,
        box-shadow 0.15s ease !important;
}

.primary-button:hover {
    background: #8d7fff !important;
}

.primary-button:active {
    background: #6a59f0 !important;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.35) !important;
}

.primary-button:focus-visible {
    outline: 2px solid var(--accent-2) !important;
    outline-offset: 2px !important;
}

/*
 * Legend chips of AnnotatedImage.
 * Gradio assigns a translucent per-label background inline, so leave it
 * alone and only strengthen the contrast of the text on top of it.
 */
.legend-item {
    color: #ffffff !important;
    font-weight: 700 !important;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.35);
}

footer {
    display: none !important;
}
"""

def build_gradio_app() -> gr.Blocks:
    with gr.Blocks(
        title=APP_TITLE,
    ) as demo:
        gr.HTML(
            """
            <div class="app-header">
                <div class="brand">
                    <div class="brand-icon">◈</div>
                    <div>
                        <div class="brand-title">
                            VISION MARKER
                        </div>
                        <div class="brand-subtitle">
                            Local object detection
                        </div>
                    </div>
                </div>

                <div class="status-pill">
                    <span class="status-dot"></span>
                    LOCAL AI READY
                </div>
            </div>
            """
        )

        with gr.Row(equal_height=True):
            with gr.Column(
                scale=4,
                elem_classes=["app-panel"],
            ):
                gr.Markdown("### INPUT IMAGE")

                input_image = gr.Image(
                    type="pil",
                    image_mode="RGB",
                    # No "clipboard": its paste button relies on
                    # navigator.clipboard.read(), which never delivers an image
                    # inside pywebview on either Windows or Linux.
                    sources=[
                        "upload",
                        "webcam",
                    ],
                    label="Drop an image",
                    height=450,
                )

                analyze_button = gr.Button(
                    "START ANALYSIS",
                    variant="primary",
                    elem_classes=["primary-button"],
                )

            with gr.Column(
                scale=6,
                elem_classes=["app-panel"],
            ):
                gr.Markdown("### OBJECT DETECTION")

                annotated_output = gr.AnnotatedImage(
                    label=DETECTION_LABEL,
                    height=540,
                    show_legend=True,
                )

        with gr.Row():
            with gr.Column(elem_classes=["app-panel"]):
                detection_threshold = gr.Slider(
                    minimum=0.1,
                    maximum=0.95,
                    value=0.7,
                    step=0.05,
                    label="Detection threshold",
                )

        with gr.Row():
            with gr.Column(elem_classes=["app-panel"]):
                gr.Markdown("### DETECTION REPORT")

                report_output = gr.Markdown(
                    "Select an image and press START ANALYSIS."
                )

        analyze_button.click(
            fn=analyze_image,
            inputs=[
                input_image,
                detection_threshold,
            ],
            outputs=[
                annotated_output,
                report_output,
            ],
            show_progress="full",
            show_progress_on=[annotated_output],
        )

    return demo


# ============================================================
# pywebview startup
# ============================================================

def run_gradio_server() -> None:
    demo = build_gradio_app()
    demo.queue()

    # This call blocks, so it must run on a background thread
    demo.launch(
        server_name=HOST,
        server_port=PORT,
        css=CUSTOM_CSS,
        footer_links=[],
        prevent_thread_lock=False,
    )


def wait_for_server(
    url: str,
    timeout_seconds: float = 60.0,
) -> None:
    """
    Wait for Gradio to come up before showing the pywebview window.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                url,
                timeout=1,
            ) as response:
                if response.status < 500:
                    return
        except Exception as exception:
            last_error = exception
            time.sleep(0.25)

    raise RuntimeError(
        f"Could not start the Gradio server: {last_error}"
    )


def main() -> None:
    server_thread = threading.Thread(
        target=run_gradio_server,
        daemon=True,
    )
    server_thread.start()

    wait_for_server(APP_URL)

    webview.create_window(
        title=APP_TITLE,
        # Pin Gradio's own theme to dark; without this it follows the OS
        # setting and renders light against our dark custom CSS
        url=f"{APP_URL}/?__theme=dark",
        width=1360,
        height=900,
        min_size=(1000, 700),
        resizable=True,
        background_color="#090B12",
        text_select=True,
    )

    # The pywebview GUI loop must start on the main thread.
    #
    # The gui argument matches the platform markers in pyproject.toml. Without
    # it pywebview probes GTK first on Linux and logs a traceback before
    # falling back to Qt.
    webview.start(
        gui="qt" if sys.platform == "linux" else None,
        debug=False,
        private_mode=False,
    )


if __name__ == "__main__":
    main()
