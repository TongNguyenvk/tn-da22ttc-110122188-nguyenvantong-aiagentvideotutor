"""
Sequential Pipeline - Kien truc tuan tu (don gian nhat)
Quay xong -> Tao document
"""
import logging
import json
from pathlib import Path
from typing import Dict, List

from core.screenshot_capture import ScreenshotCapture
from renderers.video_renderer import VideoRenderer
from renderers.document_renderer import DocumentRenderer
from renderers.pdf_renderer import PDFRenderer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SequentialPipeline:
    """Pipeline tuan tu: Execute -> Video -> Document"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        self.screenshot_capture = ScreenshotCapture(output_dir)
        self.video_renderer = VideoRenderer(output_dir)
        self.document_renderer = DocumentRenderer(output_dir)
        self.pdf_renderer = PDFRenderer(output_dir)
    
    def run(self, plan: Dict) -> Dict[str, str]:
        """
        Chay pipeline tuan tu
        
        Args:
            plan: Plan tu AI (steps, narration, etc.)
        
        Returns:
            Dict chua path cua cac output
        """
        logger.info("=" * 80)
        logger.info("SEQUENTIAL PIPELINE - Bat dau")
        logger.info("=" * 80)
        
        # Phase 1: Execute + Capture screenshots
        logger.info("\nPhase 1: Execute + Capture screenshots")
        artifacts = self._collect_artifacts(plan)
        
        # Luu artifacts ra disk
        self._save_artifacts(artifacts)
        
        # Phase 2: Render video
        logger.info("\nPhase 2: Render video")
        video_path = self.video_renderer.render(plan, artifacts)
        
        # Phase 3: Render document
        logger.info("\nPhase 3: Render document")
        doc_path = self.document_renderer.render(plan, artifacts)
        
        # Phase 4: Render PDF
        logger.info("\nPhase 4: Render PDF")
        pdf_path = self.pdf_renderer.render(plan, artifacts)
        
        results = {
            'video': video_path,
            'document': doc_path,
            'pdf': pdf_path
        }
        
        logger.info("\n" + "=" * 80)
        logger.info("SEQUENTIAL PIPELINE - Hoan thanh")
        logger.info(f"Video: {video_path}")
        logger.info(f"Document: {doc_path}")
        logger.info(f"PDF: {pdf_path}")
        logger.info("=" * 80)
        
        return results
    
    def _collect_artifacts(self, plan: Dict) -> Dict:
        """Thu thap artifacts (screenshots, audio, etc.)"""
        artifacts = {
            'screenshots': [],
            'audio': [],
            'metadata': {}
        }
        
        steps = plan.get('steps', [])
        
        for i, step in enumerate(steps):
            logger.info(f"  Executing step {i+1}/{len(steps)}: {step.get('narration', '')[:50]}...")
            
            # TODO: Thuc thi step tren browser/desktop
            # Hien tai chi chup anh man hinh
            screenshot_path = self.screenshot_capture.capture_step(i)
            if screenshot_path:
                artifacts['screenshots'].append(screenshot_path)
        
        return artifacts
    
    def _save_artifacts(self, artifacts: Dict):
        """Luu artifacts ra disk"""
        artifacts_path = self.output_dir / "artifacts.json"
        
        # Convert Path objects to strings for JSON serialization
        serializable_artifacts = {
            'screenshots': [str(p) for p in artifacts['screenshots']],
            'audio': [str(p) for p in artifacts['audio']],
            'metadata': artifacts['metadata']
        }
        
        with open(artifacts_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_artifacts, f, indent=2, ensure_ascii=False)
        
        logger.info(f"  Artifacts saved: {artifacts_path}")
