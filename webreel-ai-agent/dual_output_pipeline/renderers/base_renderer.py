"""
Base Renderer - Abstract class cho tat ca renderer
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from pathlib import Path

class Renderer(ABC):
    """Abstract base class cho tat ca renderer"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
    
    @abstractmethod
    def render(self, plan: Dict, artifacts: Dict) -> str:
        """
        Render output tu plan va artifacts
        
        Args:
            plan: Plan tu AI (steps, narration, etc.)
            artifacts: Screenshots, audio, etc.
        
        Returns:
            Path to output file
        """
        pass
    
    @property
    @abstractmethod
    def output_format(self) -> str:
        """Format cua output (mp4, docx, pdf, etc.)"""
        pass
