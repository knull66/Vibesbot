#!/usr/bin/env python3
"""
Crear fondo profesional para DMG de Vibesbot
"""
import struct
import zlib
import os
from pathlib import Path

def create_png(width, height, pixels):
    """Create a PNG file from pixel data"""
    def png_chunk(chunk_type, data):
        chunk_len = struct.pack('>I', len(data))
        chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)
        return chunk_len + chunk_type + data + chunk_crc
    
    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'
    
    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = png_chunk(b'IHDR', ihdr_data)
    
    # IDAT chunk (image data)
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # Filter byte
        for x in range(width):
            idx = (y * width + x) * 3
            raw_data += bytes(pixels[idx:idx+3])
    
    compressed = zlib.compress(raw_data, 9)
    idat = png_chunk(b'IDAT', compressed)
    
    # IEND chunk
    iend = png_chunk(b'IEND', b'')
    
    return signature + ihdr + idat + iend

def create_dmg_background():
    """Create professional DMG background"""
    width = 540
    height = 380
    
    # Create pixel array (RGB)
    pixels = []
    
    # Background gradient with cyberpunk grid
    for y in range(height):
        for x in range(width):
            # Base dark gradient
            base_r = int(10 + (y / height) * 5)
            base_g = int(10 + (y / height) * 15)
            base_b = int(15 + (y / height) * 20)
            
            # Add subtle grid lines
            grid_intensity = 0
            if x % 30 < 2 or y % 30 < 2:
                grid_intensity = 10
            
            # Add glow from center bottom
            center_x = width // 2
            center_y = height + 50
            dist = ((x - center_x)**2 + (y - center_y)**2) ** 0.5
            glow = max(0, int(40 - dist * 0.12))
            
            r = min(255, base_r + grid_intensity)
            g = min(255, base_g + grid_intensity + glow)
            b = min(255, base_b + grid_intensity + glow)
            
            pixels.extend([r, g, b])
    
    png_data = create_png(width, height, pixels)
    
    # Save
    output_path = Path(__file__).parent / "assets" / "dmg_background.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'wb') as f:
        f.write(png_data)
    
    print(f"Created: {output_path}")
    return output_path

if __name__ == "__main__":
    create_dmg_background()
