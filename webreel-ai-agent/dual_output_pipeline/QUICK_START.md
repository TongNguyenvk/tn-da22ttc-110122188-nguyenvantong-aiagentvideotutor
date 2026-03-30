# Quick Start - Dual Output Pipeline

## Cai dat

```bash
cd dual_output_pipeline
pip install -r requirements.txt
```

## Test Sequential Pipeline

```bash
python test_sequential.py
```

Output:
- `output/test_sequential/test_sequential.mp4` (video stub)
- `output/test_sequential/test_sequential.docx` (document)
- `output/test_sequential/test_sequential.pdf` (PDF)

## Test Hybrid Pipeline (Recommended)

```bash
python test_hybrid.py
```

Output:
- `output/test_hybrid/test_hybrid.mp4` (video stub)
- `output/test_hybrid/test_hybrid.docx` (document)
- `output/test_hybrid/test_hybrid.pdf` (PDF)

## Cau truc folder

```
dual_output_pipeline/
├── core/                      # Core components
│   ├── screenshot_capture.py  # Chup man hinh
│   └── word_adapter.py        # Tu dong hoa Word
├── renderers/                 # Output renderers
│   ├── base_renderer.py       # Abstract base
│   ├── video_renderer.py      # Video (stub)
│   ├── document_renderer.py   # DOCX
│   └── pdf_renderer.py        # PDF
├── output/                    # Output files
├── pipeline_sequential.py     # Sequential architecture
├── pipeline_hybrid.py         # Hybrid architecture
├── test_sequential.py         # Test sequential
└── test_hybrid.py             # Test hybrid
```

## Buoc tiep theo

1. Tich hop voi webreel_runner de render video that
2. Tich hop voi os_recorder de execute steps
3. Them parallel pipeline
4. Them generic pluggable pipeline
