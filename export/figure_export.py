"""Export Matplotlib figures with embedded metadata."""
from __future__ import annotations

import json
from pathlib import Path
from matplotlib.figure import Figure

def export_figure(fig: Figure, path: str | Path, meta: dict | None = None) -> None:
    """Save figure as PNG (300 dpi), SVG, or PDF, optionally embedding metadata."""
    path = Path(path)
    
    # Common save options
    kwargs = {"bbox_inches": "tight"}
    if path.suffix.lower() == ".png":
        kwargs["dpi"] = 300
        # Embed metadata as PNG info if provided
        if meta:
            try:
                from PIL import Image, PngImagePlugin
                
                # First save with matplotlib
                fig.savefig(path, **kwargs)
                
                # Then reopen with PIL to inject metadata
                img = Image.open(path)
                info = PngImagePlugin.PngInfo()
                info.add_text("Software", "RAS Sediment Calibration Workbench")
                for k, v in meta.items():
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v)
                    info.add_text(f"Analysis_{k}", str(v))
                img.save(path, "PNG", pnginfo=info)
                return
            except ImportError:
                pass
                
    elif path.suffix.lower() == ".pdf":
        # Embed metadata in PDF using PdfPages or backend options
        if meta:
            metadata = {"Creator": "RAS Sediment Calibration Workbench"}
            for k, v in meta.items():
                if isinstance(v, str):
                    metadata[k] = v
            kwargs["metadata"] = metadata
            
    elif path.suffix.lower() == ".svg":
        if meta:
            metadata = {"Creator": "RAS Sediment Calibration Workbench"}
            for k, v in meta.items():
                if isinstance(v, str):
                    metadata[k] = v
            kwargs["metadata"] = metadata

    fig.savefig(path, **kwargs)
