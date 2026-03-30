"""
PDF Renderer - Tao file PDF tu plan va screenshots
"""
import logging
from pathlib import Path
from typing import Dict
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# Import base_renderer without relative import
import sys
sys.path.insert(0, str(Path(__file__).parent))
from base_renderer import Renderer

logger = logging.getLogger(__name__)

class PDFRenderer(Renderer):
    """Renderer de tao file PDF"""
    
    def render(self, plan: Dict, artifacts: Dict) -> str:
        """Tao file PDF tu plan va screenshots"""
        logger.info("  [PDFRenderer] Bat dau render PDF...")
        
        output_path = self.output_dir / f"{plan.get('name', 'tutorial')}.pdf"
        
        doc = SimpleDocTemplate(str(output_path), pagesize=A4)
        story = []
        styles = getSampleStyleSheet()
        
        # Tieu de
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor='darkblue',
            spaceAfter=30,
            alignment=TA_CENTER
        )
        title = plan.get('title', 'Tutorial')
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.5*inch))
        
        # Them tung buoc
        steps = plan.get('steps', [])
        screenshots = artifacts.get('screenshots', [])
        
        for i, step in enumerate(steps):
            narration = step.get('narration', f'Buoc {i+1}')
            
            # Tieu de buoc
            step_title = f'Buoc {i+1}: {narration}'
            story.append(Paragraph(step_title, styles['Heading2']))
            story.append(Spacer(1, 0.2*inch))
            
            # Them anh neu co
            if i < len(screenshots) and screenshots[i]:
                screenshot_path = screenshots[i]
                if Path(screenshot_path).exists():
                    try:
                        img = Image(screenshot_path, width=6*inch, height=4*inch)
                        story.append(img)
                    except Exception as e:
                        logger.error(f"  [PDFRenderer] Loi chen anh: {e}")
            
            story.append(Spacer(1, 0.3*inch))
        
        # Build PDF
        doc.build(story)
        
        logger.info(f"  [PDFRenderer] Da luu PDF: {output_path}")
        return str(output_path)
    
    @property
    def output_format(self) -> str:
        return "pdf"
