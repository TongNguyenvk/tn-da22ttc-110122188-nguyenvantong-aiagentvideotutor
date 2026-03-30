"""
Hybrid Pipeline - Kien truc lai (DE XUAT TOT NHAT)
Execute + Capture -> Luu artifacts -> Render song song
"""
import logging
import json
import asyncio
from pathlib import Path
from typing import Dict, List

from core.screenshot_capture import ScreenshotCapture
from renderers.video_renderer import VideoRenderer
from renderers.document_renderer import DocumentRenderer
from renderers.pdf_renderer import PDFRenderer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HybridPipeline:
    """Pipeline lai: Execute -> Luu artifacts -> Render song song"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        self.screenshot_capture = ScreenshotCapture(output_dir)
        self.video_renderer = VideoRenderer(output_dir)
        self.document_renderer = DocumentRenderer(output_dir)
        self.pdf_renderer = PDFRenderer(output_dir)
    
    def run(self, plan: Dict) -> Dict[str, str]:
        """
        Chay pipeline lai
        
        Args:
            plan: Plan tu AI (steps, narration, etc.)
        
        Returns:
            Dict chua path cua cac output
        """
        logger.info("=" * 80)
        logger.info("HYBRID PIPELINE - Bat dau")
        logger.info("=" * 80)
        
        # Phase 1: Execute + Capture (DONG BO)
        logger.info("\nPhase 1: Execute + Capture screenshots")
        artifacts = self._collect_artifacts(plan)
        
        # Luu artifacts ra disk
        artifacts_path = self._save_artifacts(artifacts, plan)
        
        # Phase 2: Render outputs SONG SONG (BAT DONG BO)
        logger.info("\nPhase 2: Render outputs (parallel)")
        results = asyncio.run(self._render_all_outputs(plan, artifacts))
        
        logger.info("\n" + "=" * 80)
        logger.info("HYBRID PIPELINE - Hoan thanh")
        logger.info(f"Video: {results['video']}")
        logger.info(f"Document: {results['document']}")
        logger.info(f"PDF: {results['pdf']}")
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
    
    def _save_artifacts(self, artifacts: Dict, plan: Dict) -> Path:
        """Luu artifacts va plan ra disk"""
        # Luu artifacts
        artifacts_path = self.output_dir / "artifacts.json"
        serializable_artifacts = {
            'screenshots': [str(p) for p in artifacts['screenshots']],
            'audio': [str(p) for p in artifacts['audio']],
            'metadata': artifacts['metadata']
        }
        
        with open(artifacts_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_artifacts, f, indent=2, ensure_ascii=False)
        
        # Luu plan
        plan_path = self.output_dir / "plan.json"
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        
        logger.info(f"  Artifacts saved: {artifacts_path}")
        logger.info(f"  Plan saved: {plan_path}")
        
        return plan_path
    
    async def _render_all_outputs(self, plan: Dict, artifacts: Dict) -> Dict[str, str]:
        """Render tat ca output song song"""
        tasks = [
            self._render_video_async(plan, artifacts),
            self._render_document_async(plan, artifacts),
            self._render_pdf_async(plan, artifacts)
        ]
        
        results = await asyncio.gather(*tasks)
        
        return {
            'video': results[0],
            'document': results[1],
            'pdf': results[2]
        }
    
    async def _render_video_async(self, plan: Dict, artifacts: Dict) -> str:
        """Render video bat dong bo"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.video_renderer.render, plan, artifacts)
    
    async def _render_document_async(self, plan: Dict, artifacts: Dict) -> str:
        """Render document bat dong bo"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.document_renderer.render, plan, artifacts)
    
    async def _render_pdf_async(self, plan: Dict, artifacts: Dict) -> str:
        """Render PDF bat dong bo"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.pdf_renderer.render, plan, artifacts)
