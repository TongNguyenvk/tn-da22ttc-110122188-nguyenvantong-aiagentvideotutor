# Dual Output Pipeline - Experimental

Folder thử nghiệm cho tính năng Dual-Output (Video + Document).

## Cấu trúc

```
dual_output_pipeline/
├── core/                   # Core components từ os_recorder
│   ├── word_adapter.py    # Tự động hóa Word
│   ├── screenshot_capture.py  # Chụp màn hình
│   └── ...
├── renderers/             # Các renderer cho output
│   ├── base_renderer.py   # Abstract base class
│   ├── video_renderer.py  # Render video
│   ├── document_renderer.py  # Render DOCX
│   └── pdf_renderer.py    # Render PDF
├── output/                # Output files
├── pipeline_sequential.py # Sequential architecture
├── pipeline_parallel.py   # Parallel architecture
├── pipeline_hybrid.py     # Hybrid architecture (recommended)
├── pipeline_generic.py    # Generic pluggable architecture
├── test_sequential.py     # Test sequential
├── test_hybrid.py         # Test hybrid
└── requirements.txt       # Dependencies

## Kiến trúc

Xem docs/DUAL_OUTPUT_ARCHITECTURES.md để hiểu chi tiết các kiến trúc.

## Quick Start

```bash
# Cài đặt dependencies
pip install -r requirements.txt

# Test Sequential
python test_sequential.py

# Test Hybrid (recommended)
python test_hybrid.py
```

## Ghi chú

- Folder này KHÔNG ảnh hưởng đến code production
- Dùng để thử nghiệm và prototype
- Sau khi stable sẽ merge vào desktop_app
