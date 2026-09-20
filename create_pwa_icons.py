#!/usr/bin/env python3
"""
Generate PWA icons for Vibesbot.
Creates icons in multiple sizes for PWA manifest.
"""
from PIL import Image, ImageDraw
from pathlib import Path

def create_icon(size: int, output_path: Path):
    """Create a single icon at the specified size."""
    
    # Create image with dark background
    img = Image.new('RGBA', (size, size), (5, 5, 8, 255))
    draw = ImageDraw.Draw(img)
    
    # Calculate proportions
    padding = size // 8
    inner_size = size - (padding * 2)
    
    # Draw rounded rectangle background
    rect_padding = padding
    draw.rounded_rectangle(
        [rect_padding, rect_padding, size - rect_padding, size - rect_padding],
        radius=size // 6,
        fill=(15, 19, 24, 255),
        outline=(0, 255, 255, 255),
        width=max(2, size // 64)
    )
    
    # Draw bunny face (simplified)
    center_x = size // 2
    center_y = size // 2
    
    # Face circle
    face_radius = inner_size // 3
    face_left = center_x - face_radius
    face_top = center_y - face_radius + (size // 10)
    face_right = center_x + face_radius
    face_bottom = center_y + face_radius + (size // 10)
    
    # Draw face outline with glow effect
    for i in range(3, 0, -1):
        glow_color = (0, 255, 255, 50 * i)
        draw.ellipse(
            [face_left - i*2, face_top - i*2, face_right + i*2, face_bottom + i*2],
            outline=glow_color,
            width=max(1, size // 100)
        )
    
    # Main face
    draw.ellipse(
        [face_left, face_top, face_right, face_bottom],
        outline=(0, 255, 255, 255),
        width=max(2, size // 50)
    )
    
    # Ears
    ear_width = face_radius // 2
    ear_height = face_radius
    
    # Left ear
    left_ear_x = center_x - face_radius + ear_width // 2
    left_ear_top = face_top - ear_height + (size // 20)
    draw.ellipse(
        [left_ear_x - ear_width//2, left_ear_top, 
         left_ear_x + ear_width//2, face_top + ear_height//3],
        outline=(0, 255, 255, 255),
        width=max(2, size // 50)
    )
    
    # Right ear
    right_ear_x = center_x + face_radius - ear_width // 2
    draw.ellipse(
        [right_ear_x - ear_width//2, left_ear_top,
         right_ear_x + ear_width//2, face_top + ear_height//3],
        outline=(0, 255, 255, 255),
        width=max(2, size // 50)
    )
    
    # Eyes (glowing horizontal lines)
    eye_y = center_y + (size // 20)
    eye_width = face_radius // 3
    eye_height = max(2, size // 40)
    
    # Left eye
    left_eye_x = center_x - face_radius // 2
    draw.rectangle(
        [left_eye_x - eye_width//2, eye_y - eye_height//2,
         left_eye_x + eye_width//2, eye_y + eye_height//2],
        fill=(0, 255, 255, 255)
    )
    # Glow
    for i in range(3):
        glow_alpha = 100 - i * 30
        draw.rectangle(
            [left_eye_x - eye_width//2 - i*2, eye_y - eye_height//2 - i,
             left_eye_x + eye_width//2 + i*2, eye_y + eye_height//2 + i],
            outline=(0, 255, 255, glow_alpha)
        )
    
    # Right eye
    right_eye_x = center_x + face_radius // 2
    draw.rectangle(
        [right_eye_x - eye_width//2, eye_y - eye_height//2,
         right_eye_x + eye_width//2, eye_y + eye_height//2],
        fill=(0, 255, 255, 255)
    )
    # Glow
    for i in range(3):
        glow_alpha = 100 - i * 30
        draw.rectangle(
            [right_eye_x - eye_width//2 - i*2, eye_y - eye_height//2 - i,
             right_eye_x + eye_width//2 + i*2, eye_y + eye_height//2 + i],
            outline=(0, 255, 255, glow_alpha)
        )
    
    # Save
    img.save(output_path, 'PNG')
    print(f"  Created: {output_path.name}")

def main():
    """Generate all PWA icons."""
    
    icons_dir = Path(__file__).parent / "web" / "static" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    
    print("Creating PWA icons...")
    
    for size in sizes:
        output_path = icons_dir / f"icon-{size}.png"
        create_icon(size, output_path)
    
    print(f"\nCreated {len(sizes)} icons in {icons_dir}")

if __name__ == "__main__":
    main()
