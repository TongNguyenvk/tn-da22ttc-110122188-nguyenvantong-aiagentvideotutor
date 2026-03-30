"""
Full Demo Pipeline - Vua quay video vua chup hinh thuc te
Tich hop webreel de quay video + screenshot de tao document
"""
import logging
import json
import asyncio
import time
import sys
from pathlib import Path
from typing import Dict, List

# Add desktop_app to path
DESKTOP_APP_DIR = Path(__file__).parent.parent / "desktop_app"
sys.path.insert(0, str(DESKTOP_APP_DIR))

from core.screenshot_capture import ScreenshotCapture
from renderers.video_renderer import VideoRenderer
from renderers.document_renderer import DocumentRenderer
from renderers.pdf_renderer import PDFRenderer

# Import webreel runner
try:
    from webreel_runner import record_video_with_webreel
except ImportError:
    record_video_with_webreel = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FullDemoPipeline:
    """Pipeline day du: Quay video + Chup hinh + Tao document"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        self.screenshot_capture = ScreenshotCapture(output_dir)
        self.video_renderer = VideoRenderer(output_dir)
        self.document_renderer = DocumentRenderer(output_dir)
        self.pdf_renderer = PDFRenderer(output_dir)
    
    def run(self, webreel_config: Dict, video_name: str) -> Dict[str, str]:
        """
        Chay pipeline day du
        
        Args:
            webreel_config: Config cho webreel
            video_name: Ten video
        
        Returns:
            Dict chua path cua cac output
        """
        logger.info("=" * 80)
        logger.info("FULL DEMO PIPELINE - Bat dau")
        logger.info("=" * 80)
        
        # Phase 1: Chuan bi plan tu webreel config
        logger.info("\nPhase 1: Chuan bi plan")
        plan = self._prepare_plan(webreel_config, video_name)
        
        # Phase 2: Quay video + Chup hinh DONG THOI
        logger.info("\nPhase 2: Quay video + Chup hinh (parallel)")
        video_path, artifacts = self._record_and_capture(webreel_config, plan, video_name)
        
        # Luu artifacts
        self._save_artifacts(artifacts, plan)
        
        # Phase 3: Render document va PDF SONG SONG
        logger.info("\nPhase 3: Render document va PDF (parallel)")
        doc_results = asyncio.run(self._render_documents(plan, artifacts))
        
        results = {
            'video': str(video_path) if video_path else None,
            'document': doc_results['document'],
            'pdf': doc_results['pdf']
        }
        
        logger.info("\n" + "=" * 80)
        logger.info("FULL DEMO PIPELINE - Hoan thanh")
        logger.info(f"Video: {results['video']}")
        logger.info(f"Document: {results['document']}")
        logger.info(f"PDF: {results['pdf']}")
        logger.info("=" * 80)
        
        return results
    
    def _prepare_plan(self, webreel_config: Dict, video_name: str) -> Dict:
        """Chuan bi plan tu webreel config"""
        video_config = webreel_config.get('videos', {}).get(video_name, {})
        steps = video_config.get('steps', [])
        
        plan = {
            'name': video_name,
            'title': f'Demo: {video_name}',
            'steps': []
        }
        
        for i, step in enumerate(steps):
            plan['steps'].append({
                'action': step.get('action', 'unknown'),
                'narration': step.get('description', f'Buoc {i+1}'),
                'selector': step.get('selector', ''),
                'value': step.get('value', '')
            })
        
        return plan
    
    def _record_and_capture(self, webreel_config: Dict, plan: Dict, video_name: str):
        """Quay video va chup hinh dong thoi"""
        artifacts = {
            'screenshots': [],
            'audio': [],
            'metadata': {}
        }
        
        # Luu config ra file
        config_path = self.output_dir / f"{video_name}_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(webreel_config, f, indent=2)
        
        logger.info(f"  Config saved: {config_path}")
        
        # Neu co webreel_runner, quay video that
        video_path = None
        if record_video_with_webreel:
            try:
                logger.info("  Bat dau quay video voi webreel...")
                video_path = record_video_with_webreel(
                    webreel_config, 
                    config_path, 
                    video_name
                )
                logger.info(f"  Video da quay: {video_path}")
            except Exception as e:
                logger.error(f"  Loi quay video: {e}")
        else:
            logger.warning("  webreel_runner khong kha dung, bo qua quay video")
        
        # Chup hinh man hinh cho moi buoc
        logger.info("  Bat dau chup hinh man hinh...")
        for i, step in enumerate(plan['steps']):
            logger.info(f"    Chup hinh buoc {i+1}/{len(plan['steps'])}: {step.get('narration', '')[:50]}...")
            
            # Doi 1 chut de man hinh on dinh
            time.sleep(0.5)
            
            # Chup hinh
            screenshot_path = self.screenshot_capture.capture_step(i)
            if screenshot_path:
                artifacts['screenshots'].append(screenshot_path)
        
        return video_path, artifacts
    
    def _save_artifacts(self, artifacts: Dict, plan: Dict):
        """Luu artifacts ra disk"""
        artifacts_path = self.output_dir / "artifacts.json"
        serializable_artifacts = {
            'screenshots': [str(p) for p in artifacts['screenshots']],
            'audio': [str(p) for p in artifacts['audio']],
            'metadata': artifacts['metadata']
        }
        
        with open(artifacts_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_artifacts, f, indent=2, ensure_ascii=False)
        
        plan_path = self.output_dir / "plan.json"
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        
        logger.info(f"  Artifacts saved: {artifacts_path}")
        logger.info(f"  Plan saved: {plan_path}")
    
    async def _render_documents(self, plan: Dict, artifacts: Dict) -> Dict[str, str]:
        """Render document va PDF song song"""
        tasks = [
            self._render_document_async(plan, artifacts),
            self._render_pdf_async(plan, artifacts)
        ]
        
        results = await asyncio.gather(*tasks)
        
        return {
            'document': results[0],
            'pdf': results[1]
        }
    
    async def _render_document_async(self, plan: Dict, artifacts: Dict) -> str:
        """Render document bat dong bo"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.document_renderer.render, plan, artifacts)
    
    async def _render_pdf_async(self, plan: Dict, artifacts: Dict) -> str:
        """Render PDF bat dong bo"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.pdf_renderer.render, plan, artifacts)
